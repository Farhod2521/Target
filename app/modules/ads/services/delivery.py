"""A running ad group's delivery settings: the price of a result, which results count, how often it shows.

Meta keeps these three on the ad set and the mirror does not, so the form
asks Meta when it is opened and a save is checked against what Meta holds at
that moment. The rules are the launch's own (``core.targeting.budget``,
``core.targeting.attribution``): a price ceiling only where the goal is
bought by the result, a window only where results are counted on a site, a
frequency cap only where the goal is being seen.
"""

import logging
from dataclasses import dataclass
from typing import Any, Final

from adskit import ExternalRef
from adskit.dto import ActionResult
from adskit.errors import ProviderError
from metaads import delivery as meta_delivery
from metaads.delivery import Delivery
from metaads.launcher import MetaLauncher
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.exceptions import DomainError
from app.common.money import format_minor, provider_money
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.exceptions import (
    CampaignFinished,
    ChangeRefused,
    CostCapNotOffered,
    CostCapTooLow,
    DeliveryOptionUnusable,
    DeliveryUnreadable,
    NothingChanged,
)
from app.modules.ads.models import AdSet
from app.modules.ads.selectors.delivery_options import MAX_CAP_DAYS
from app.modules.ads.services.manage import (
    DELIVERY,
    Planned,
    _live,
    record,
    state_of,
    state_payload,
    target_for,
)
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from core.agent import check_limit_change
from core.agent.guardrails import REFUSED_FINISHED
from core.targeting import accepts_cap, takes_attribution, windows_for
from core.targeting.attribution import DEFAULT_WINDOW, attribution_window
from core.targeting.budget import FREQUENCY_GOALS, min_daily_for_cap

logger = logging.getLogger(__name__)

LEVEL: Final = ManagedLevel.ADSET
MAX_CAP_TIMES: Final = 50
# The request's keys. A key that is absent is a setting nobody asked about.
CAP: Final = "cap_minor"
WINDOW: Final = "window"
FREQUENCY: Final = "frequency"


@dataclass(frozen=True, slots=True)
class Held:
    """One group's settings as Meta holds them, and which of them it may take."""

    group: AdSet
    now: Delivery
    readable: bool
    offers_cap: bool
    offers_window: bool
    offers_frequency: bool
    can_change: bool

    @property
    def window_key(self) -> str:
        """The window's name here; Meta's own default where it holds none."""
        if self.now.window is None:
            return DEFAULT_WINDOW
        return next(
            (
                row.key
                for row in windows_for(provider=self.group.provider)
                if (row.click_days, row.view_days) == self.now.window
            ),
            "",
        )


def held(group: AdSet) -> Held:
    """What this group holds now. An unreadable answer is said, never guessed as empty."""
    goal = str(group.optimization_goal_raw or "").upper()
    now, readable = _read(group)
    return Held(
        group=group,
        now=now,
        readable=readable,
        # The budget's holder bids: under a campaign budget the strategy is
        # the campaign's, and a group's own would be refused.
        offers_cap=accepts_cap(goal)
        and group.daily_budget_minor is not None
        and not now.foreign_bid,
        offers_window=takes_attribution(goal),
        offers_frequency=goal in FREQUENCY_GOALS,
        can_change=readable and check_limit_change(state=state_of(group)).allowed,
    )


def _read(group: AdSet) -> tuple[Delivery, bool]:
    from app.modules.ads.services.access import target_account_and_token

    if settings.ads_dry_run:
        return Delivery(), True
    try:
        _account, token = target_account_and_token(target=group, level=LEVEL)
        row = MetaLauncher().adset_settings(
            adset=ExternalRef(
                provider=group.provider, level=LEVEL, id=str(group.external_id)
            ),  # type: ignore[arg-type]
            token=token,
        )
    except (ProviderError, DomainError):
        logger.info("could not read the delivery settings of %s", group.external_id)
        return Delivery(), False
    return meta_delivery.read(row), True


def plan_delivery(
    db: Session,
    *,
    user: User,
    external_id: str,
    asked: dict[str, Any],
) -> Planned:
    """One change of whichever settings ``asked`` names and Meta holds otherwise.

    ``cap_minor`` 0 removes the ceiling; ``window`` is a window's key;
    ``frequency`` is ``[times, days]`` and ``[]`` removes the cap.
    """
    _live(db, user)
    now = held(
        target_for(db, user=user, level=LEVEL, external_id=external_id, aspect=DELIVERY)
    )
    if not now.readable:
        raise DeliveryUnreadable
    verdict = check_limit_change(state=state_of(now.group))
    if not verdict.allowed:
        raise {REFUSED_FINISHED: CampaignFinished}.get(verdict.reason, ChangeRefused)()
    wanted: dict[str, Any] = {}
    previous: dict[str, Any] = {}
    if CAP in asked:
        cap = _cap(now, int(asked[CAP] or 0))
        if cap != (now.now.cap_minor or 0):
            wanted[CAP], previous[CAP] = cap, now.now.cap_minor or 0
    if WINDOW in asked:
        key = _window(now, str(asked[WINDOW] or ""))
        if key != now.window_key:
            wanted[WINDOW], previous[WINDOW] = key, now.window_key
    if FREQUENCY in asked:
        cap_of = _frequency(now, asked[FREQUENCY])
        before = list(now.now.frequency or ())
        if cap_of != before:
            wanted[FREQUENCY], previous[FREQUENCY] = cap_of, before
    if not wanted:
        raise NothingChanged
    return Planned(
        target=now.group,
        level=LEVEL,
        external_id=external_id,
        action=ActionType.DELIVERY_SET,
        requested=wanted,
        previous=state_payload(now.group) | {"delivery": previous},
        dispatch=_dispatch,
    )


def _cap(now: Held, cap_minor: int) -> int:
    if cap_minor < 0:
        raise DeliveryOptionUnusable
    if not now.offers_cap:
        raise CostCapNotOffered
    daily = int(now.group.daily_budget_minor or 0)
    needed = min_daily_for_cap(cap_minor=cap_minor)
    if cap_minor and daily < needed:
        currency = str(now.group.currency or "")
        places = provider_money(provider=now.group.provider).decimal_places(currency)
        raise CostCapTooLow(
            needed=format_minor(amount_minor=needed, currency=currency, places=places)
        )
    return cap_minor


def _window(now: Held, key: str) -> str:
    if not now.offers_window:
        raise DeliveryOptionUnusable
    if attribution_window(provider=now.group.provider, key=key) is None:
        raise DeliveryOptionUnusable
    return key


def _frequency(now: Held, asked: object) -> list[int]:
    if not now.offers_frequency:
        raise DeliveryOptionUnusable
    if not asked:
        return []
    if not isinstance(asked, list | tuple) or len(asked) != 2:
        raise DeliveryOptionUnusable
    times, days = int(asked[0]), int(asked[1])
    if not 1 <= times <= MAX_CAP_TIMES or not 1 <= days <= MAX_CAP_DAYS:
        raise DeliveryOptionUnusable
    return [times, days]


def _dispatch(log_id: str) -> None:
    from app.modules.ads.tasks import apply_delivery_task

    apply_delivery_task.delay(log_id)


def apply_delivery(db: Session, *, log_id: str) -> str:
    """One audit row, carried out. Returns a word for the task's log line."""
    from app.modules.ads.actions.executor import Write, carry_out

    return carry_out(
        db,
        log_id=log_id,
        kind=Write(
            actions=frozenset({ActionType.DELIVERY_SET}),
            write=_write,
            finish=_finish,
        ),
    )


def fields_for(log: ActionLog) -> dict[str, Any]:
    """Meta's fields for what this change asks."""
    asked = log.request_payload or {}
    window = None
    if WINDOW in asked:
        row = attribution_window(provider=log.target_provider, key=str(asked[WINDOW]))
        window = (row.click_days, row.view_days) if row is not None else None
    cap = int(asked.get(CAP) or 0)
    frequency = asked.get(FREQUENCY)
    return meta_delivery.payload(
        cap_minor=cap or None,
        remove_cap=CAP in asked and not cap,
        window=window,
        frequency=(int(frequency[0]), int(frequency[1])) if frequency else None,
        remove_frequency=FREQUENCY in asked and not frequency,
    )


def _write(db: Session, job: Any) -> ActionResult:
    data = fields_for(job.log)
    MetaLauncher().set_adset_delivery(
        adset=job.ref, data=data, token=job.token, dry_run=job.dry_run
    )
    return ActionResult(
        ok=True,
        ref=job.ref,
        applied={"delivery": dict(job.log.request_payload or {})},
        dry_run=job.dry_run,
    )


def _finish(db: Session, job: Any, result: ActionResult) -> None:
    record(
        db,
        log=job.log,
        target=job.target,
        result=result,
        before=job.before,
        after=None,
    )


__all__ = [
    "CAP",
    "FREQUENCY",
    "MAX_CAP_TIMES",
    "WINDOW",
    "Held",
    "apply_delivery",
    "fields_for",
    "held",
    "plan_delivery",
]
