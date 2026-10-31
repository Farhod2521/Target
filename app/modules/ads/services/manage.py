"""Changing a live advert: pause, resume, budget, end date, spend cap, audience.

A plan checks the guardrails against the mirror; opening it writes a PENDING
ActionLog (callers ask through :mod:`app.modules.ads.actions`); the worker (``apply_change``) checks again against the provider,
writes, reads back and records. The commit that opens the log is the
caller's, and the worker task is sent after it.
"""

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final

from adskit import ExternalRef
from adskit.dto import ActionResult, StatusDTO
from adskit.errors import PermissionDenied, ProviderError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import on_commit, utcnow
from app.common.exceptions import DomainError
from app.common.money import provider_money
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    ACTION_STALE_MINUTES,
    BLOCKED_STANDINGS,
    MANAGE_LOG_PREFIX,
    ManagedLevel,
)
from app.modules.ads.exceptions import (
    AccountNotConnected,
    AlreadyInState,
    BudgetBelowMinimum,
    CampaignFinished,
    ChangeInFlight,
    ChangeRefused,
    ForeignAudience,
    GroupStillLearning,
    LastAdInGroup,
    LearningInProgress,
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
from app.modules.audit.constants import ActionStatus, ActionType, ActorType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from app.modules.integrations.models import AdAccount
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


def fail_log(
    db: Session,
    *,
    log: ActionLog,
    code: str,
    message: str,
    detail: dict[str, str] | None = None,
) -> None:
    """``detail`` is what the provider wrote for the advertiser, quoted under
    the screen's own sentence."""
    log.status = str(ActionStatus.FAILED)
    log.error_code = code[:32]
    log.error_message = message
    if detail:
        log.result_payload = {**(log.result_payload or {}), **detail}
    db.commit()


def close_stalled_changes(db: Session, *, now: datetime) -> int:
    """Give up on every pause or resume no worker carried out in time.

    Past this the screens stop waiting, so the row would only stay open for
    good. A late task finds it closed and leaves it.
    """
    rows = db.scalars(
        select(ActionLog).where(
            ActionLog.status == str(ActionStatus.PENDING),
            ActionLog.action.in_([str(action) for action in STATUS_WANTED]),
            ActionLog.created_at < now - timedelta(minutes=ACTION_STALE_MINUTES),
        )
    ).all()
    for log in rows:
        fail_log(db, log=log, code="stalled", message="no worker carried it out")
    return len(rows)


# A provider's refusal by class name, so adding a provider never means
# importing its exceptions here. Anything not named is a refusal.
PROVIDER_FAILURES: Final[dict[str, str]] = {
    "AuthFailed": "reconnect",
    "PermissionDenied": "permission",
    "AccountActionRequired": "account_action",
    "PaymentMethodMissing": "payment_missing",
    "RateLimited": "temporary",
    "TemporaryFailure": "temporary",
    "NotFound": "not_found",
}


def fail_provider(
    db: Session, *, log: ActionLog, exc: ProviderError, account: AdAccount | None
) -> None:
    """A refusal under the word the screen reads; the provider's own code goes
    into the message. A refused write on a blocked account is the account's,
    not the profile's: Meta answers both with the same permission error."""
    code = PROVIDER_FAILURES.get(type(exc).__name__, "refused")
    if (
        code == "permission"
        and account is not None
        and (account.may_advertise is False or account.standing in BLOCKED_STANDINGS)
    ):
        code = "account_blocked"
    fail_log(
        db,
        log=log,
        code=code,
        message=f"[{exc.code}] {exc}" if exc.code else str(exc),
        detail={
            key: value
            for key, value in (
                ("user_title", exc.user_title),
                ("user_message", exc.user_message),
                ("key", exc.key),
            )
            if value
        },
    )
    _explain_later(db, log)


def _explain_later(db: Session, log: ActionLog) -> None:
    """A refusal the screen has no sentence for goes to be explained, in the owner's language.

    After the row is committed, so a lost broker never turns a refusal into
    an unknown failure.
    """
    from app.modules.ads.selectors.failures import unfamiliar
    from app.modules.chat.selectors.change_refusal import change_key
    from app.modules.chat.services.explain import count_refusal, explain_later

    if not unfamiliar(log):
        return
    try:
        explain_later(log=log, language=log.owner.language)
        count_refusal(db, key=change_key(log))
        db.commit()
    except Exception:
        logger.exception("refusal %s was not sent to be explained", log.id)


def refused_by_provider(
    db: Session,
    *,
    log: ActionLog,
    exc: ProviderError,
    account: AdAccount,
    port: Any,
    token: str,
) -> None:
    """Record the refusal; a permission refusal reads the account's money first,
    so a blocked account is told apart from a missing role."""
    if isinstance(exc, PermissionDenied):
        from app.modules.ads.services.stops import refresh_account_state

        refresh_account_state(db, ad_account=account, campaigns=port, token=token)
    fail_provider(db, log=log, exc=exc, account=account)


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


@dataclass(frozen=True, slots=True)
class Planned:
    """A change every check passed, and everything opening it needs.

    What :func:`app.modules.ads.actions.preview` answers: a screen or the
    assistant can say what will happen from it, and nothing has been opened.
    """

    target: Any
    level: str
    external_id: str
    action: str
    requested: dict[str, Any]
    previous: dict[str, Any] | None = None
    dispatch: Callable[[str], Any] | None = None
    # A change another one can undo carries the id of the one it undoes.
    revertible: bool = True

    @property
    def provider(self) -> str:
        return str(self.target.provider)


def open_planned(
    db: Session,
    *,
    user: User,
    plan: Planned,
    origin: Origin = BY_HAND,
    reverts: str = "",
) -> ActionLog:
    requested = dict(plan.requested)
    if plan.revertible:
        requested["reverts"] = reverts
    return open_change(
        db,
        user=user,
        target=plan.target,
        level=plan.level,
        external_id=plan.external_id,
        action=plan.action,
        requested=requested,
        previous=plan.previous,
        origin=origin,
        dispatch=plan.dispatch,
    )


def plan_status(
    db: Session, *, user: User, level: str, external_id: str, wanted: str
) -> Planned:
    target = status_gate(
        db, user=user, level=level, external_id=external_id, wanted=wanted
    )
    return Planned(
        target=target,
        level=level,
        external_id=external_id,
        action=ActionType.PAUSE if wanted == PAUSED else ActionType.RESUME,
        requested={"status": wanted},
    )


def plan_budget(
    db: Session, *, user: User, level: str, external_id: str, daily_budget_minor: int
) -> Planned:
    target, account = budget_gate(
        db,
        user=user,
        level=level,
        external_id=external_id,
        daily_budget_minor=daily_budget_minor,
    )
    current = getattr(target, "daily_budget_minor", None) or 0
    return Planned(
        target=target,
        level=level,
        external_id=external_id,
        action=ActionType.BUDGET_UP
        if daily_budget_minor > current
        else ActionType.BUDGET_DOWN,
        requested={
            "daily_budget_minor": daily_budget_minor,
            "currency": account.currency,
        },
    )


def budget_gate(
    db: Session, *, user: User, level: str, external_id: str, daily_budget_minor: int
) -> tuple[Any, Any]:
    """Every check a budget change passes, without opening one. Raises the refusal."""
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
    return target, account


def status_gate(
    db: Session, *, user: User, level: str, external_id: str, wanted: str
) -> Any:
    """Every check a pause or a resume passes, without opening one. Raises the refusal."""
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
    return target


def plan_end_time(
    db: Session, *, user: User, external_id: str, end_time: datetime
) -> Planned:
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
    return Planned(
        target=target,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        action=ActionType.END_TIME_SET,
        requested={"end_time": end_time.isoformat()},
        previous=state_payload(target)
        | {"end_time": previous.isoformat() if previous else ""},
    )


def plan_spend_cap(
    db: Session, *, user: User, external_id: str, spend_cap_minor: int
) -> Planned:
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
    return Planned(
        target=target,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        action=ActionType.SPEND_CAP_SET,
        requested={"spend_cap_minor": spend_cap_minor},
        previous=state_payload(target)
        | {"spend_cap_minor": getattr(target, "spend_cap_minor", None)},
    )


def plan_targeting(
    db: Session,
    *,
    user: User,
    external_id: str,
    targeting: Mapping[str, Any],
    step: str = "",
    origin: Origin = BY_HAND,
) -> Planned:
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
    return Planned(
        target=target,
        level="adset",
        external_id=external_id,
        action=ActionType.TARGETING_SWAP,
        requested={"targeting": dict(targeting), "step": step},
        previous=state_payload(target) | {"targeting": previous},
    )


def parse_datetime(value: str) -> datetime | None:

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
    """A switch, a budget, a limit or an audience, carried out."""
    from app.modules.ads.actions.executor import Write, carry_out

    return carry_out(
        db,
        log_id=log_id,
        kind=Write(
            actions=frozenset(WRITES),
            check=_check_change,
            write=_write_change,
            finish=_finish_change,
        ),
    )


def _check_change(db: Session, job: Any) -> str:
    refusal = _refused(
        db,
        log=job.log,
        before=job.before,
        target=job.target,
        port=job.provider.campaigns,
        token=job.token,
    )
    return refusal or _moved_elsewhere(
        log=job.log,
        target=job.target,
        provider=job.provider,
        ref=job.ref,
        token=job.token,
    )


def _write_change(db: Session, job: Any) -> ActionResult:
    return _write(
        log=job.log,
        provider=job.provider,
        ref=job.ref,
        token=job.token,
        dry_run=job.dry_run,
    )


def _finish_change(db: Session, job: Any, result: ActionResult) -> None:
    after = _read_back(
        port=job.provider.campaigns,
        ref=job.ref,
        token=job.token,
        dry_run=result.dry_run,
    )
    record(
        db,
        log=job.log,
        target=job.target,
        result=result,
        before=job.before,
        after=after,
        landed=_landed(log=job.log, after=after),
    )
    if not result.dry_run:
        _read_below(db, job)


def _read_below(db: Session, job: Any) -> None:
    """A switch above decides what everything under it delivers: read that too."""
    level = job.log.target_level
    if job.log.action not in STATUS_WANTED or level == ManagedLevel.AD:
        return
    adsets = list(job.target.adsets) if level == ManagedLevel.CAMPAIGN else []
    ads = [ad for adset in adsets or [job.target] for ad in adset.ads]
    rows = {row.external_id: row for row in [*adsets, *ads]}
    refs = [
        ExternalRef(provider=job.ref.provider, level=at, id=row.external_id)
        for at, group in ((ManagedLevel.ADSET, adsets), (ManagedLevel.AD, ads))
        for row in group
    ]
    try:
        found = job.provider.campaigns.read_objects(
            account=ExternalRef(
                provider=job.ref.provider, level="account", id=job.account.external_id
            ),
            refs=refs,
            token=job.token,
        )
    except ProviderError:
        logger.info("could not read what is under %s after the write", job.ref)
        return
    for dto in (*found.adsets, *found.ads):
        row = rows[dto.ref.id]
        row.status = dto.status
        row.effective_status = dto.effective_status
        row.delivery = dto.delivery
    db.flush()


def _moved_elsewhere(
    *, log: ActionLog, target: Any, provider: Any, ref: ExternalRef, token: str
) -> str:
    """Why this audience must not be replaced now, or nothing.

    The spec goes out whole, built on the copy the owner was shown. When the
    ad set holds another audience by now - changed in Ads Manager, or trimmed
    by Meta itself - that copy would undo the change. The mirror takes what
    Meta holds, and the owner looks again before saving.
    """
    if log.action != ActionType.TARGETING_SWAP or settings.ads_dry_run:
        return ""
    seen = (log.previous_state or {}).get("targeting")
    if not isinstance(seen, dict) or not seen:
        return ""
    try:
        live = provider.audiences.read_targeting(ref=ref, token=token)
    except ProviderError as exc:
        logger.info("could not read %s before replacing its audience: %s", ref, exc)
        return "read"
    if provider.audiences.same_targeting(seen, live):
        return ""
    if live and hasattr(target, "targeting_raw"):
        target.targeting_raw = live
    return "changed_elsewhere"


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
    except ProviderError:
        logger.info("could not read %s before switching an ad off", parent_ref)
        return "read"
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
        return field, parse_datetime(str(result.applied.get("end_time", "")))
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


# -- switching a chain on --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Activation:
    opened: tuple[ActionLog, ...]
    refused: tuple[str, ...]


def start_delivery(
    db: Session,
    *,
    user: User,
    targets: Sequence[tuple[str, str]],
    origin: Origin = BY_HAND,
) -> Activation:
    """Resume the campaign and what below it never started, top first."""
    from app.modules.ads.exceptions import NothingToStart

    if not targets:
        raise UnknownTarget
    opened: list[ActionLog] = []
    refused: list[str] = []
    for level, external_id in targets:
        try:
            plan = plan_status(
                db, user=user, level=level, external_id=external_id, wanted=ACTIVE
            )
            opened.append(open_planned(db, user=user, plan=plan, origin=origin))
        except AlreadyInState:
            continue
        except DomainError as exc:
            logger.info("could not start %s:%s - %s", level, external_id, exc)
            if exc.message not in refused:
                refused.append(exc.message)
            if level == ManagedLevel.CAMPAIGN:
                break
    if not opened and not refused:
        raise NothingToStart
    return Activation(opened=tuple(opened), refused=tuple(refused))
