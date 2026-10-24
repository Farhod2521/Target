"""Changing a live advert: pause, resume, budget, end date, spend cap, audience.

A request checks the guardrails against the mirror and opens a PENDING
ActionLog; the worker (``apply_change``) checks again against the provider,
writes, reads back and records. The commit that opens the log is the
caller's, and the worker task is sent after it.
"""

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from adskit import ExternalRef, registry
from adskit.dto import ActionResult, StatusDTO
from adskit.errors import AccountActionRequired, ProviderError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import on_commit, utcnow
from app.common.exceptions import DomainError
from app.common.money import provider_money
from app.modules.accounts.models import User
from app.modules.ads.constants import MANAGE_LOG_PREFIX, ManagedLevel
from app.modules.ads.exceptions import (
    AccountNotConnected,
    AlreadyInState,
    BudgetBelowMinimum,
    CampaignFinished,
    ChangeInFlight,
    ChangeRefused,
    ConnectionUnusable,
    ForeignAudience,
    GroupStillLearning,
    LastAdInGroup,
    LearningInProgress,
    NoAdAccount,
    NothingToRevert,
    UnknownTarget,
)
from app.modules.ads.models import Ad
from app.modules.ads.selectors import (
    account_of,
    budget_floor,
    campaigns_switched_on,
    counted_by_tier,
    in_flight,
    launched_campaign_ids,
    managed_target,
    shared_adset_ids,
    shared_campaign_ids,
)
from app.modules.ads.services.access import target_account_and_token
from app.modules.audit.constants import ActionStatus, ActionType, ActorType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from core.agent import (
    AdContext,
    ObjectState,
    check_ad_pause,
    check_budget_change,
    check_limit_change,
    check_status_change,
    check_targeting_change,
)
from core.agent.guardrails import (
    ACTIVE,
    PAUSED,
    REFUSED_ALREADY,
    REFUSED_BELOW_FLOOR,
    REFUSED_FINISHED,
    REFUSED_LAST_AD,
    REFUSED_LEARNING,
)
from core.targeting import daily_floor

logger = logging.getLogger(__name__)


# -- who asked --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Origin:
    actor_type: str = ActorType.USER
    run_id: str = ""


BY_HAND = Origin()
BY_SYSTEM = Origin(actor_type=ActorType.SYSTEM)


def by_agent(run_id: str) -> Origin:
    return Origin(actor_type=ActorType.AGENT, run_id=run_id)


# -- the log --------------------------------------------------------------------------


def next_key(db: Session, *, level: str, external_id: str) -> str:
    prefix = f"{MANAGE_LOG_PREFIX}:{level}:{external_id}:"
    attempt = (
        db.scalar(
            select(func.count(ActionLog.id)).where(
                ActionLog.idempotency_key.startswith(prefix)
            )
        )
        or 0
    ) + 1
    return f"{prefix}{attempt}"


def open_log(
    db: Session,
    *,
    owner: User,
    action: str,
    provider: str,
    level: str,
    external_id: str,
    requested: dict[str, Any],
    previous: dict[str, Any],
    dry_run: bool,
    origin: Origin = BY_HAND,
) -> ActionLog:
    log = ActionLog(
        owner_id=owner.id,
        actor_type=str(origin.actor_type),
        actor_id=owner.id,
        run_id=uuid.UUID(origin.run_id) if origin.run_id else None,
        action=str(action),
        target_provider=provider,
        target_level=str(level),
        target_external_id=external_id,
        request_payload=requested,
        previous_state=previous,
        status=str(ActionStatus.PENDING),
        dry_run=dry_run,
        idempotency_key=next_key(db, level=level, external_id=external_id),
    )
    db.add(log)
    db.flush()
    return log


def close_log(
    db: Session,
    *,
    log: ActionLog,
    result: ActionResult,
    previous: dict[str, Any],
    landed: bool | None = None,
) -> None:
    log.status = str(ActionStatus.APPLIED)
    log.previous_state = previous
    log.result_payload = dict(result.applied) | (
        {} if landed is None else {"landed": landed}
    )
    log.dropped = dict(result.dropped)
    log.dry_run = result.dry_run
    log.applied_at = utcnow()
    db.flush()


def fail_log(db: Session, *, log: ActionLog, code: str, message: str) -> None:
    log.status = str(ActionStatus.FAILED)
    log.error_code = code[:32]
    log.error_message = message
    db.commit()


# -- the gate ---------------------------------------------------------------------------

STATUS: Final = "status"
BUDGET: Final = "budget"
TARGETING: Final = "targeting"
END_TIME: Final = "end_time"
SPEND_CAP: Final = "spend_cap"
CREATIVE: Final = "creative"
REMOVAL: Final = "removal"
_DELETES = {ActionType.DELETE_CAMPAIGN, ActionType.DELETE_ADSET, ActionType.DELETE_AD}
ASPECT_ACTIONS: Final[dict[str, frozenset[str]]] = {
    STATUS: frozenset({ActionType.PAUSE, ActionType.RESUME, *_DELETES}),
    BUDGET: frozenset({ActionType.BUDGET_UP, ActionType.BUDGET_DOWN}),
    TARGETING: frozenset({ActionType.TARGETING_SWAP}),
    END_TIME: frozenset({ActionType.END_TIME_SET}),
    SPEND_CAP: frozenset({ActionType.SPEND_CAP_SET}),
    CREATIVE: frozenset({ActionType.CREATIVE_SWAP}),
    REMOVAL: frozenset(_DELETES),
}


def target_for(
    db: Session, *, user: User, level: str, external_id: str, aspect: str
) -> Any:
    target = managed_target(db, owner=user, level=level, external_id=external_id)
    if target is None:
        raise UnknownTarget
    if not account_of(target=target, level=level).is_active:
        raise AccountNotConnected
    if in_flight(
        db,
        owner=user,
        level=level,
        external_id=external_id,
        actions=ASPECT_ACTIONS.get(aspect, frozenset()),
    ):
        raise ChangeInFlight
    return target


def state_of(target: Any) -> ObjectState:
    return ObjectState(
        delivery=str(getattr(target, "delivery", "unknown")),
        is_learning=bool(getattr(target, "is_learning", False)),
        daily_budget_minor=getattr(target, "daily_budget_minor", None),
    )


def state_payload(target: Any) -> dict[str, Any]:
    return {
        "status": getattr(target, "status", ""),
        "delivery": str(getattr(target, "delivery", "")),
        "daily_budget_minor": getattr(target, "daily_budget_minor", None),
        "from_mirror": True,
    }


def _default_dispatch(log_id: str) -> None:
    from app.modules.ads.tasks import apply_change_task

    apply_change_task.delay(log_id)


def open_change(
    db: Session,
    *,
    user: User,
    target: Any,
    level: str,
    external_id: str,
    action: str,
    requested: dict[str, Any],
    previous: dict[str, Any] | None = None,
    origin: Origin = BY_HAND,
    dispatch: Callable[[str], Any] | None = None,
) -> ActionLog:
    send = dispatch if dispatch is not None else _default_dispatch
    try:
        with db.begin_nested():
            log = open_log(
                db,
                owner=user,
                action=action,
                provider=target.provider,
                level=level,
                external_id=external_id,
                requested=requested,
                previous=previous if previous is not None else state_payload(target),
                dry_run=bool(settings.ads_dry_run),
                origin=origin,
            )
    except IntegrityError as exc:
        logger.info("second press on %s:%s turned away", level, external_id)
        raise ChangeInFlight from exc
    log_id = str(log.id)
    on_commit(db, lambda: send(log_id))
    return log


# -- the trial's allowance --------------------------------------------------------------


def check_campaign_allowance(
    db: Session, *, owner: User, external_id: str = ""
) -> None:
    from app.modules.billing.selectors import trial_in_progress

    trial = trial_in_progress(db, owner=owner)
    if trial is None:
        return
    if external_id and external_id in shared_campaign_ids(db, owner=owner):
        return
    _check_trial_turn(db, owner=owner, since=trial.started_at, external_id=external_id)


def check_adset_allowance(db: Session, *, owner: User, external_id: str) -> None:
    from app.modules.billing.selectors import trial_in_progress

    trial = trial_in_progress(db, owner=owner)
    if trial is not None and external_id in shared_adset_ids(db, owner=owner):
        _check_trial_turn(
            db, owner=owner, since=trial.started_at, external_id=external_id
        )


def _check_trial_turn(
    db: Session, *, owner: User, since: datetime, external_id: str
) -> None:
    from app.modules.billing.constants import TRIAL_MAX_CAMPAIGNS
    from app.modules.billing.exceptions import TrialLimitReached

    already = campaigns_switched_on(db, owner=owner, since=since)
    if external_id and external_id in already:
        return
    if len(already) >= TRIAL_MAX_CAMPAIGNS:
        raise TrialLimitReached(limit=TRIAL_MAX_CAMPAIGNS)


# -- asking for a change ------------------------------------------------------------------

BUDGET_ACTIONS: frozenset[str] = frozenset(
    {ActionType.BUDGET_UP, ActionType.BUDGET_DOWN}
)
LIMIT_ACTIONS: frozenset[str] = frozenset(
    {ActionType.END_TIME_SET, ActionType.SPEND_CAP_SET}
)
REFUSALS: dict[str, type[DomainError]] = {
    REFUSED_ALREADY: AlreadyInState,
    REFUSED_FINISHED: CampaignFinished,
    REFUSED_LEARNING: LearningInProgress,
}
AD_REFUSALS: dict[str, type[DomainError]] = REFUSALS | {
    REFUSED_LEARNING: GroupStillLearning,
    REFUSED_LAST_AD: LastAdInGroup,
}


def _live(db: Session, user: User) -> None:
    from app.modules.billing.services import require_live_subscription

    require_live_subscription(db, owner=user)


def _has_spent(db: Session, *, owner: User, adset_id: str) -> bool:
    from app.modules.metrics.selectors import has_spent

    return has_spent(db, owner=owner, adset_id=adset_id)


def _ad_context(db: Session, *, owner: User, target: Any) -> AdContext:
    from app.modules.ads.constants import Delivery

    parent = getattr(target, "adset", None)
    if parent is None:
        return AdContext()
    others = db.scalar(
        select(func.count(Ad.id)).where(
            Ad.owner_id == owner.id,
            Ad.adset_id == parent.id,
            Ad.delivery == str(Delivery.ACTIVE),
            Ad.id != target.id,
        )
    )
    return AdContext(
        parent_is_learning=bool(getattr(parent, "is_learning", False)),
        other_active_ads=others or 0,
    )


def request_pause(
    db: Session, *, user: User, level: str, external_id: str, origin: Origin = BY_HAND
) -> ActionLog:
    return request_status(
        db,
        user=user,
        level=level,
        external_id=external_id,
        wanted=PAUSED,
        origin=origin,
    )


def request_resume(
    db: Session, *, user: User, level: str, external_id: str, origin: Origin = BY_HAND
) -> ActionLog:
    return request_status(
        db,
        user=user,
        level=level,
        external_id=external_id,
        wanted=ACTIVE,
        origin=origin,
    )


def request_budget(
    db: Session,
    *,
    user: User,
    level: str,
    external_id: str,
    daily_budget_minor: int,
    reverts: str = "",
    origin: Origin = BY_HAND,
) -> ActionLog:
    _live(db, user)
    target = target_for(
        db, user=user, level=level, external_id=external_id, aspect=BUDGET
    )
    account = account_of(target=target, level=level)
    floor = budget_floor(target=target, level=level)
    state = state_of(target)
    if level == ManagedLevel.ADSET and state.is_learning:
        state = replace(
            state, has_spent=_has_spent(db, owner=user, adset_id=external_id)
        )
    verdict = check_budget_change(
        state=state, wanted_minor=daily_budget_minor, floor_minor=floor
    )
    if not verdict.allowed:
        if verdict.reason == REFUSED_BELOW_FLOOR:
            raise BudgetBelowMinimum(
                minimum_minor=floor,
                currency=account.currency,
                places=provider_money(provider=account.provider).decimal_places(
                    account.currency
                ),
            )
        raise REFUSALS.get(verdict.reason, ChangeRefused)()
    current = getattr(target, "daily_budget_minor", None) or 0
    return open_change(
        db,
        user=user,
        target=target,
        level=level,
        external_id=external_id,
        action=ActionType.BUDGET_UP
        if daily_budget_minor > current
        else ActionType.BUDGET_DOWN,
        requested={
            "daily_budget_minor": daily_budget_minor,
            "currency": account.currency,
            "reverts": reverts,
        },
        origin=origin,
    )


def request_status(
    db: Session,
    *,
    user: User,
    level: str,
    external_id: str,
    wanted: str,
    reverts: str = "",
    origin: Origin = BY_HAND,
) -> ActionLog:
    if wanted == ACTIVE:
        _live(db, user)
    target = target_for(
        db, user=user, level=level, external_id=external_id, aspect=STATUS
    )
    state = state_of(target)
    counted = wanted == ACTIVE and counted_by_tier(
        db, owner=user, account=account_of(target=target, level=level)
    )
    if counted and level == ManagedLevel.CAMPAIGN:
        check_campaign_allowance(db, owner=user, external_id=external_id)
    if counted and level == ManagedLevel.ADSET:
        check_adset_allowance(db, owner=user, external_id=external_id)
    if level == ManagedLevel.AD and wanted == PAUSED:
        verdict = check_ad_pause(
            state=state, parent=_ad_context(db, owner=user, target=target)
        )
        if not verdict.allowed:
            raise AD_REFUSALS.get(verdict.reason, ChangeRefused)()
    else:
        verdict = check_status_change(state=state, wanted=wanted)
        if not verdict.allowed:
            raise REFUSALS.get(verdict.reason, ChangeRefused)()
    return open_change(
        db,
        user=user,
        target=target,
        level=level,
        external_id=external_id,
        action=ActionType.PAUSE if wanted == PAUSED else ActionType.RESUME,
        requested={"status": wanted, "reverts": reverts},
        origin=origin,
    )


def request_end_time(
    db: Session,
    *,
    user: User,
    external_id: str,
    end_time: datetime,
    reverts: str = "",
    origin: Origin = BY_HAND,
) -> ActionLog:
    _live(db, user)
    target = target_for(
        db,
        user=user,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        aspect=END_TIME,
    )
    verdict = check_limit_change(state=state_of(target))
    if not verdict.allowed:
        raise {REFUSED_FINISHED: CampaignFinished}.get(verdict.reason, ChangeRefused)()
    previous = getattr(target, "end_time", None)
    return open_change(
        db,
        user=user,
        target=target,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        action=ActionType.END_TIME_SET,
        requested={"end_time": end_time.isoformat(), "reverts": reverts},
        previous=state_payload(target)
        | {"end_time": previous.isoformat() if previous else ""},
        origin=origin,
    )


def request_spend_cap(
    db: Session,
    *,
    user: User,
    external_id: str,
    spend_cap_minor: int,
    reverts: str = "",
    origin: Origin = BY_HAND,
) -> ActionLog:
    _live(db, user)
    if spend_cap_minor <= 0:
        raise ChangeRefused
    target = target_for(
        db,
        user=user,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        aspect=SPEND_CAP,
    )
    verdict = check_limit_change(state=state_of(target))
    if not verdict.allowed:
        raise {REFUSED_FINISHED: CampaignFinished}.get(verdict.reason, ChangeRefused)()
    return open_change(
        db,
        user=user,
        target=target,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        action=ActionType.SPEND_CAP_SET,
        requested={"spend_cap_minor": spend_cap_minor, "reverts": reverts},
        previous=state_payload(target)
        | {"spend_cap_minor": getattr(target, "spend_cap_minor", None)},
        origin=origin,
    )


def request_targeting(
    db: Session,
    *,
    user: User,
    external_id: str,
    targeting: Mapping[str, Any],
    step: str = "",
    reverts: str = "",
    origin: Origin = BY_HAND,
) -> ActionLog:
    _live(db, user)
    if not targeting:
        raise ChangeRefused
    target = target_for(
        db, user=user, level="adset", external_id=external_id, aspect=TARGETING
    )
    verdict = check_targeting_change(state=state_of(target))
    if not verdict.allowed:
        raise {
            REFUSED_FINISHED: CampaignFinished,
            REFUSED_LEARNING: LearningInProgress,
        }.get(verdict.reason, ChangeRefused)()
    if origin.actor_type == ActorType.AGENT:
        campaign = getattr(target, "campaign", None)
        campaign_id = str(getattr(campaign, "external_id", "") or "")
        ours = bool(campaign_id) and campaign_id in launched_campaign_ids(
            db, owner=user, ad_account=getattr(campaign, "ad_account", None)
        )
        if not ours:
            raise ForeignAudience
    previous = getattr(target, "targeting_raw", None)
    if not isinstance(previous, dict) or not previous:
        raise UnknownTarget
    return open_change(
        db,
        user=user,
        target=target,
        level="adset",
        external_id=external_id,
        action=ActionType.TARGETING_SWAP,
        requested={"targeting": dict(targeting), "step": step, "reverts": reverts},
        previous=state_payload(target) | {"targeting": previous},
        origin=origin,
    )


def request_revert(db: Session, *, user: User, log_id: str) -> ActionLog:
    _live(db, user)
    try:
        pk = uuid.UUID(str(log_id))
    except ValueError:
        raise NothingToRevert from None
    original = db.scalars(
        select(ActionLog).where(
            ActionLog.owner_id == user.id,
            ActionLog.id == pk,
            ActionLog.status == str(ActionStatus.APPLIED),
        )
    ).first()
    if original is None or original.dry_run:
        raise NothingToRevert
    previous = original.previous_state
    level, external_id = original.target_level, original.target_external_id
    reverts = str(original.id)
    if original.action in BUDGET_ACTIONS:
        amount = previous.get("daily_budget_minor")
        if amount is None:
            raise NothingToRevert
        return request_budget(
            db,
            user=user,
            level=level,
            external_id=external_id,
            daily_budget_minor=int(amount),
            reverts=reverts,
        )
    if original.action == ActionType.TARGETING_SWAP:
        spec = previous.get("targeting")
        if not isinstance(spec, dict) or not spec:
            raise NothingToRevert
        return request_targeting(
            db, user=user, external_id=external_id, targeting=spec, reverts=reverts
        )
    if original.action == ActionType.END_TIME_SET:
        stamp = _parse_datetime(str(previous.get("end_time") or ""))
        if stamp is None:
            raise NothingToRevert
        return request_end_time(
            db, user=user, external_id=external_id, end_time=stamp, reverts=reverts
        )
    if original.action == ActionType.SPEND_CAP_SET:
        ceiling = previous.get("spend_cap_minor")
        if ceiling is None:
            raise NothingToRevert
        return request_spend_cap(
            db,
            user=user,
            external_id=external_id,
            spend_cap_minor=int(ceiling),
            reverts=reverts,
        )
    if original.action == ActionType.CREATIVE_SWAP:
        raise NothingToRevert
    wanted = str(previous.get("delivery", ""))
    if wanted not in (ACTIVE, PAUSED):
        raise NothingToRevert
    return request_status(
        db,
        user=user,
        level=level,
        external_id=external_id,
        wanted=wanted,
        reverts=reverts,
    )


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


# -- the worker's half ------------------------------------------------------------------

STATUS_WANTED: dict[str, str] = {ActionType.PAUSE: PAUSED, ActionType.RESUME: ACTIVE}
WRITES: frozenset[str] = (
    frozenset(STATUS_WANTED)
    | BUDGET_ACTIONS
    | LIMIT_ACTIONS
    | {ActionType.TARGETING_SWAP}
)
EVENTS: dict[str, str] = {
    ActionType.PAUSE: EventName.CAMPAIGN_PAUSED,
    ActionType.RESUME: EventName.CAMPAIGN_ACTIVATED,
    ActionType.BUDGET_UP: EventName.BUDGET_CHANGED,
    ActionType.BUDGET_DOWN: EventName.BUDGET_CHANGED,
    ActionType.TARGETING_SWAP: EventName.TARGETING_CHANGED,
    ActionType.END_TIME_SET: EventName.BUDGET_CHANGED,
    ActionType.SPEND_CAP_SET: EventName.BUDGET_CHANGED,
    ActionType.CREATIVE_SWAP: EventName.CREATIVE_CHANGED,
}
LIMIT_FIELDS: dict[str, str] = {
    ActionType.END_TIME_SET: "end_time",
    ActionType.SPEND_CAP_SET: "spend_cap_minor",
}


def apply_change(db: Session, *, log_id: str) -> str:
    log = db.get(ActionLog, uuid.UUID(str(log_id)))
    if log is None:
        return "gone"
    if log.status != ActionStatus.PENDING:
        return "done"
    if log.action not in WRITES:
        fail_log(db, log=log, code="unknown", message=f"no write for {log.action}")
        return "unknown"
    target = managed_target(
        db, owner=log.owner, level=log.target_level, external_id=log.target_external_id
    )
    if target is None:
        fail_log(db, log=log, code="gone", message="object is no longer in the mirror")
        return "gone"
    try:
        account, token = target_account_and_token(target=target, level=log.target_level)
    except (NoAdAccount, ConnectionUnusable) as exc:
        fail_log(db, log=log, code="connection", message=exc.message)
        return "unusable"
    ref = ExternalRef(
        provider=log.target_provider, level=log.target_level, id=log.target_external_id
    )
    try:
        provider = registry.get(log.target_provider)
        port = provider.campaigns
        before = port.get_status(ref=ref, token=token)
    except ProviderError as exc:
        fail_log(db, log=log, code=exc.code or "read", message=str(exc))
        return "failed"
    except Exception as exc:
        logger.exception("change %s could not be prepared", log.id)
        fail_log(db, log=log, code="unknown", message=str(exc))
        return "failed"
    refusal = _refused(
        db, log=log, before=before, target=target, port=port, token=token
    )
    if refusal:
        fail_log(db, log=log, code=refusal, message="the check before the write failed")
        return "refused"
    try:
        result = _write(
            log=log,
            provider=provider,
            ref=ref,
            token=token,
            dry_run=bool(settings.ads_dry_run),
        )
    except ProviderError as exc:
        if isinstance(exc, AccountActionRequired):
            from app.modules.integrations.services import note_action_required

            note_action_required(db, connection=account.connection)
        fail_log(db, log=log, code=exc.code or "write", message=str(exc))
        return "failed"
    except Exception as exc:
        logger.exception("change %s failed unexpectedly", log.id)
        fail_log(db, log=log, code="unknown", message=str(exc))
        return "failed"
    after = _read_back(port=port, ref=ref, token=token, dry_run=result.dry_run)
    record(
        db,
        log=log,
        target=target,
        result=result,
        before=before,
        after=after,
        landed=_landed(log=log, after=after),
    )
    db.commit()
    return "applied"


def _landed(*, log: ActionLog, after: StatusDTO | None) -> bool | None:
    if after is None:
        return None
    wanted = STATUS_WANTED.get(log.action)
    if wanted is not None:
        return after.delivery == wanted
    if log.action in BUDGET_ACTIONS:
        asked = log.request_payload.get("daily_budget_minor")
        if asked is None or after.daily_budget_minor is None:
            return None
        return int(after.daily_budget_minor) == int(asked)
    return None


def _refused(
    db: Session,
    *,
    log: ActionLog,
    before: StatusDTO,
    target: Any,
    port: Any,
    token: str,
) -> str:
    state = ObjectState(
        delivery=before.delivery,
        is_learning=before.is_learning,
        daily_budget_minor=before.daily_budget_minor,
    )
    if log.target_level == ManagedLevel.AD and log.action == ActionType.PAUSE:
        return _ad_refusal(
            db, log=log, state=state, target=target, port=port, token=token
        )
    if log.action == ActionType.TARGETING_SWAP:
        verdict = check_targeting_change(state=state)
    elif log.action in LIMIT_ACTIONS:
        verdict = check_limit_change(state=state)
    elif log.action in BUDGET_ACTIONS:
        if state.is_learning and log.target_level == ManagedLevel.ADSET:
            state = replace(
                state,
                has_spent=_has_spent(
                    db, owner=log.owner, adset_id=log.target_external_id
                ),
            )
        verdict = check_budget_change(
            state=state,
            wanted_minor=int(log.request_payload.get("daily_budget_minor", 0)),
            floor_minor=daily_floor(
                account_minor=_floor_source(target),
                optimization_goal=getattr(target, "optimization_goal_raw", ""),
            ),
        )
    else:
        verdict = check_status_change(state=state, wanted=STATUS_WANTED[log.action])
    return "" if verdict.allowed else verdict.reason


def _ad_refusal(
    db: Session,
    *,
    log: ActionLog,
    state: ObjectState,
    target: Any,
    port: Any,
    token: str,
) -> str:
    parent = getattr(target, "adset", None)
    parent_id = str(getattr(parent, "external_id", "") or "")
    if not parent_id:
        return "gone"
    parent_ref = ExternalRef(
        provider=log.target_provider, level=ManagedLevel.ADSET, id=parent_id
    )
    try:
        found = port.get_status(ref=parent_ref, token=token)
    except ProviderError as exc:
        logger.info("could not read %s before switching an ad off", parent_ref)
        return exc.code or "read"
    context = _ad_context(db, owner=log.owner, target=target)
    verdict = check_ad_pause(
        state=state,
        parent=AdContext(
            parent_is_learning=found.is_learning,
            other_active_ads=context.other_active_ads,
        ),
    )
    return "" if verdict.allowed else verdict.reason


def _floor_source(target: Any) -> int:
    account = getattr(target, "ad_account", None) or getattr(
        getattr(target, "campaign", None), "ad_account", None
    )
    return int(getattr(account, "min_daily_budget_minor", 0) or 0)


def _write(
    *, log: ActionLog, provider: Any, ref: ExternalRef, token: str, dry_run: bool
) -> ActionResult:
    payload = log.request_payload
    if log.action == ActionType.TARGETING_SWAP:
        return provider.audiences.apply(
            ref=ref, targeting=dict(payload["targeting"]), token=token, dry_run=dry_run
        )
    if log.action in BUDGET_ACTIONS:
        return provider.campaigns.set_budget(
            ref=ref,
            daily_budget_minor=int(payload["daily_budget_minor"]),
            token=token,
            dry_run=dry_run,
        )
    if log.action == ActionType.END_TIME_SET:
        return provider.campaigns.set_end_time(
            ref=ref, end_time=str(payload["end_time"]), token=token, dry_run=dry_run
        )
    if log.action == ActionType.SPEND_CAP_SET:
        return provider.campaigns.set_spend_cap(
            ref=ref,
            spend_cap_minor=int(payload["spend_cap_minor"]),
            token=token,
            dry_run=dry_run,
        )
    return provider.campaigns.set_status(
        ref=ref, status=STATUS_WANTED[log.action], token=token, dry_run=dry_run
    )


def _read_back(
    *, port: Any, ref: ExternalRef, token: str, dry_run: bool
) -> StatusDTO | None:
    if dry_run:
        return None
    try:
        return port.get_status(ref=ref, token=token)
    except ProviderError:
        logger.info("could not re-read %s after the write", ref)
        return None


def record(
    db: Session,
    *,
    log: ActionLog,
    target: Any,
    result: ActionResult,
    before: StatusDTO,
    after: StatusDTO | None,
    landed: bool | None = None,
) -> None:
    close_log(
        db,
        log=log,
        result=result,
        previous=_snapshot(before) | _kept(log),
        landed=landed,
    )
    original_id = str(log.request_payload.get("reverts") or "")
    if original_id:
        db.execute(
            update(ActionLog)
            .where(
                ActionLog.id == uuid.UUID(original_id),
                ActionLog.owner_id == log.owner_id,
            )
            .values(status=str(ActionStatus.REVERTED), reverted_at=utcnow())
        )
    if after is not None:
        _refresh_mirror(
            target=target,
            after=after,
            applied_targeting=result.applied.get("targeting")
            if log.action == ActionType.TARGETING_SWAP
            else None,
            applied_limit=_limit(log=log, result=result),
        )
    emit(
        db,
        owner_id=log.owner_id,
        name=EVENTS[log.action],
        aggregate_type="ad_object",
        aggregate_id=log.target_external_id,
        payload={
            "level": log.target_level,
            "provider": log.target_provider,
            "action": log.action,
            "before": _snapshot(before),
            "applied": dict(result.applied),
            "landed": landed,
            "dry_run": result.dry_run,
        },
    )
    db.flush()


def _kept(log: ActionLog) -> dict[str, Any]:
    if log.action == ActionType.TARGETING_SWAP:
        spec = log.previous_state.get("targeting")
        return {"targeting": spec} if isinstance(spec, dict) else {}
    field = LIMIT_FIELDS.get(log.action)
    if field is None:
        return {}
    return {field: log.previous_state.get(field)}


def _limit(*, log: ActionLog, result: ActionResult) -> tuple[str, Any] | None:
    field = LIMIT_FIELDS.get(log.action)
    if field is None:
        return None
    if field == "end_time":
        return field, _parse_datetime(str(result.applied.get("end_time", "")))
    return field, result.applied.get("spend_cap_minor")


def _snapshot(status: StatusDTO) -> dict[str, Any]:
    return {
        "status": status.status,
        "effective_status": status.effective_status,
        "delivery": status.delivery,
        "daily_budget_minor": status.daily_budget_minor,
        "learning_status": status.learning_status,
    }


def _refresh_mirror(
    *,
    target: Any,
    after: StatusDTO,
    applied_targeting: dict[str, Any] | None = None,
    applied_limit: tuple[str, Any] | None = None,
) -> None:
    if applied_targeting and hasattr(target, "targeting_raw"):
        target.targeting_raw = applied_targeting
    if applied_limit is not None:
        field, value = applied_limit
        if value is not None and hasattr(target, field):
            setattr(target, field, value)
    target.status = after.status
    target.effective_status = after.effective_status
    target.delivery = after.delivery
    if after.daily_budget_minor is not None and hasattr(target, "daily_budget_minor"):
        target.daily_budget_minor = int(after.daily_budget_minor)
    if hasattr(target, "is_learning"):
        target.learning_status = after.learning_status
        target.is_learning = after.is_learning
