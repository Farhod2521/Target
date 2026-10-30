"""Every change to a running advert, asked for one way.

The campaigns screen, the edit dialog, the assistant's button, the agent, the
lapse sweep: each used to call its own ``request_*`` and some ran their own
copy of the checks first, so a refusal the screen gave could be one the
assistant did not. Here a change is an *ask* - a small value naming what is
wanted - and every ask has one spec. :func:`preview` runs the spec's checks
and opens nothing; :func:`request` runs the same checks and opens the change.
Nothing else opens one.

An ask names the object by its id in the mirror; which provider it lives at
is the mirror's to say, and the plan carries it.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.exceptions import NothingToRevert
from app.modules.ads.services.manage import (
    BUDGET_ACTIONS,
    BY_HAND,
    Origin,
    Planned,
    _live,
    open_planned,
    parse_datetime,
    plan_budget,
    plan_end_time,
    plan_spend_cap,
    plan_status,
    plan_targeting,
)
from app.modules.ads.services.removal import plan_delete
from app.modules.ads.services.swap import plan_swap
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from core.agent.guardrails import ACTIVE, PAUSED


@dataclass(frozen=True, slots=True)
class Pause:
    level: str
    external_id: str


@dataclass(frozen=True, slots=True)
class Resume:
    level: str
    external_id: str


@dataclass(frozen=True, slots=True)
class Budget:
    level: str
    external_id: str
    daily_budget_minor: int


@dataclass(frozen=True, slots=True)
class EndTime:
    """An ad group's last day."""

    external_id: str
    end_time: datetime


@dataclass(frozen=True, slots=True)
class SpendCap:
    """The most a campaign may ever spend."""

    external_id: str
    spend_cap_minor: int


@dataclass(frozen=True, slots=True)
class Audience:
    """An ad group's whole audience, replaced."""

    external_id: str
    targeting: Mapping[str, Any] = field(default_factory=dict)
    step: str = ""


@dataclass(frozen=True, slots=True)
class NewAdvert:
    """The next version of an advert: what it says, shows, or the form it opens."""

    external_id: str
    message: str | None = None
    headline: str | None = None
    description: str | None = None
    asset_id: str = ""
    lead_form_id: str = ""


@dataclass(frozen=True, slots=True)
class Delete:
    level: str
    external_id: str
    # The lapse sweep removing what nobody paid for skips the subscription check.
    unpaid: bool = False


Ask = Pause | Resume | Budget | EndTime | SpendCap | Audience | NewAdvert | Delete


@dataclass(frozen=True, slots=True)
class Spec:
    """One kind of change: its name, and the checks that plan it."""

    name: str
    plan: Callable[[Session, User, Any, Origin], Planned]


SPECS: dict[type, Spec] = {
    Pause: Spec(
        "pause",
        lambda db, user, ask, _origin: plan_status(
            db, user=user, level=ask.level, external_id=ask.external_id, wanted=PAUSED
        ),
    ),
    Resume: Spec(
        "resume",
        lambda db, user, ask, _origin: plan_status(
            db, user=user, level=ask.level, external_id=ask.external_id, wanted=ACTIVE
        ),
    ),
    Budget: Spec(
        "budget",
        lambda db, user, ask, _origin: plan_budget(
            db,
            user=user,
            level=ask.level,
            external_id=ask.external_id,
            daily_budget_minor=ask.daily_budget_minor,
        ),
    ),
    EndTime: Spec(
        "end_time",
        lambda db, user, ask, _origin: plan_end_time(
            db, user=user, external_id=ask.external_id, end_time=ask.end_time
        ),
    ),
    SpendCap: Spec(
        "spend_cap",
        lambda db, user, ask, _origin: plan_spend_cap(
            db,
            user=user,
            external_id=ask.external_id,
            spend_cap_minor=ask.spend_cap_minor,
        ),
    ),
    Audience: Spec(
        "audience",
        lambda db, user, ask, origin: plan_targeting(
            db,
            user=user,
            external_id=ask.external_id,
            targeting=ask.targeting,
            step=ask.step,
            origin=origin,
        ),
    ),
    NewAdvert: Spec(
        "new_advert",
        lambda db, user, ask, _origin: plan_swap(
            db,
            user=user,
            external_id=ask.external_id,
            message=ask.message,
            headline=ask.headline,
            description=ask.description,
            asset_id=ask.asset_id,
            lead_form_id=ask.lead_form_id,
        ),
    ),
    Delete: Spec(
        "delete",
        lambda db, user, ask, _origin: plan_delete(
            db,
            user=user,
            level=ask.level,
            external_id=ask.external_id,
            unpaid=ask.unpaid,
        ),
    ),
}


def preview(db: Session, *, user: User, ask: Ask, origin: Origin = BY_HAND) -> Planned:
    """Every check the change would pass, and what it would be. Opens nothing; raises the refusal."""
    return SPECS[type(ask)].plan(db, user, ask, origin)


def request(
    db: Session,
    *,
    user: User,
    ask: Ask,
    origin: Origin = BY_HAND,
    reverts: str = "",
) -> ActionLog:
    """The same checks, and the change opened. The caller commits; the worker is sent after."""
    plan = preview(db, user=user, ask=ask, origin=origin)
    return open_planned(db, user=user, plan=plan, origin=origin, reverts=reverts)


def revert(db: Session, *, user: User, log_id: str) -> ActionLog:
    """Ask for what an applied change replaced, as a change of its own."""
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
    return request(db, user=user, ask=_undoing(original), reverts=str(original.id))


def _undoing(original: ActionLog) -> Ask:
    previous = original.previous_state or {}
    level, external_id = original.target_level, original.target_external_id
    if original.action in BUDGET_ACTIONS:
        amount = previous.get("daily_budget_minor")
        if amount is None:
            raise NothingToRevert
        return Budget(
            level=level, external_id=external_id, daily_budget_minor=int(amount)
        )
    if original.action == ActionType.TARGETING_SWAP:
        spec = previous.get("targeting")
        if not isinstance(spec, dict) or not spec:
            raise NothingToRevert
        return Audience(external_id=external_id, targeting=spec)
    if original.action == ActionType.END_TIME_SET:
        stamp = parse_datetime(str(previous.get("end_time") or ""))
        if stamp is None:
            raise NothingToRevert
        return EndTime(external_id=external_id, end_time=stamp)
    if original.action == ActionType.SPEND_CAP_SET:
        ceiling = previous.get("spend_cap_minor")
        if ceiling is None:
            raise NothingToRevert
        return SpendCap(external_id=external_id, spend_cap_minor=int(ceiling))
    if original.action not in (ActionType.PAUSE, ActionType.RESUME):
        raise NothingToRevert
    wanted = str(previous.get("delivery", ""))
    if wanted == ACTIVE:
        return Resume(level=level, external_id=external_id)
    if wanted == PAUSED:
        return Pause(level=level, external_id=external_id)
    raise NothingToRevert


__all__ = [
    "SPECS",
    "Ask",
    "Audience",
    "Budget",
    "Delete",
    "EndTime",
    "NewAdvert",
    "Pause",
    "Resume",
    "Spec",
    "SpendCap",
    "preview",
    "request",
    "revert",
]
