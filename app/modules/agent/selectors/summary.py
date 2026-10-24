"""The agent screen's status line, last night's advice cards, and the open proposals in one read."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import AdSet
from app.modules.agent.constants import RunStatus
from app.modules.agent.copy import MATURITY_LABELS, NEED_COPY, STRATEGY_COPY
from app.modules.agent.models import AgentPolicy, AgentRun
from app.modules.agent.selectors.cards import Card, pending_cards
from app.modules.agent.selectors.policy import check_is_late, policy_for
from app.modules.agent.selectors.runs import last
from app.modules.agent.selectors.suggestions import working
from core.metrics import LEAD_GOALS


@dataclass(frozen=True, slots=True)
class Summary:
    """The status strip: where this account stands, and when it was read."""

    standing: Any = ""
    last_run_at: datetime | None = None
    broken: bool = False


def agent_summary(*, run: AgentRun | None) -> Summary:
    if run is None:
        return Summary()
    return Summary(
        standing=MATURITY_LABELS.get(run.maturity, ""),
        last_run_at=run.finished_at if run.status == RunStatus.DONE else None,
        broken=run.status == RunStatus.FAILED,
    )


def has_counted_campaigns(db: Session, *, owner: User) -> bool:
    """Whether anything running here is something the cost rules can judge."""
    return (
        db.scalar(
            select(AdSet.id)
            .where(
                AdSet.owner_id == owner.id,
                AdSet.delivery == Delivery.ACTIVE,
                AdSet.optimization_goal_raw.in_(list(LEAD_GOALS)),
            )
            .limit(1)
        )
        is not None
    )


@dataclass(frozen=True, slots=True)
class AdviceCard:
    """One direction, ready to draw. A link, never a button."""

    strategy: str
    title: Any
    body: Any
    route: str
    link: Any
    ready: bool
    blocked_by: tuple[Any, ...] = ()


def advice_cards(
    db: Session, *, owner: User, run: AgentRun | None = None, page_id: str = ""
) -> list[AdviceCard]:
    """What the last pass concluded this page's advertising should do next."""
    row = run if run is not None else last(db, owner=owner)
    if row is None:
        return []
    cards = [
        _advice_card(entry)
        for entry in row.advice or ()
        if isinstance(entry, dict) and _here(entry, page_id)
    ]
    return [card for card in cards if card is not None]


def _here(entry: dict[str, Any], page_id: str) -> bool:
    written = str(entry.get("page", ""))
    return not written or not page_id or written == page_id


def _advice_card(entry: dict[str, Any]) -> AdviceCard | None:
    code = str(entry.get("strategy", ""))
    copy = STRATEGY_COPY.get(code)
    if copy is None:
        return None
    needs = [str(need) for need in entry.get("needs", []) or []]
    ready = bool(entry.get("ready", True)) and not needs
    blocking = [NEED_COPY[need] for need in needs if need in NEED_COPY]
    first = blocking[0] if blocking else None
    return AdviceCard(
        strategy=code,
        title=copy.title,
        body=copy.body,
        route=first.route if first is not None else copy.route,
        link=first.link if first is not None else copy.link,
        ready=ready,
        blocked_by=tuple(item.body for item in blocking),
    )


@dataclass(frozen=True, slots=True)
class Proposals:
    """The open proposals, and the facts a screen reads beside them."""

    cards: list[Card]
    policy: AgentPolicy | None
    working: bool
    counted: bool
    late: datetime | None


def proposals(db: Session, *, owner: User, now: datetime) -> Proposals:
    """Everything waiting for an answer from the agent on the page the owner is on."""
    from app.modules.ads.selectors import current_page_scope

    policy = policy_for(db, owner=owner)
    cards = pending_cards(
        db,
        owner=owner,
        now=now,
        scope=current_page_scope(db, owner=owner),
        cooldown_hours=policy.cooldown_hours if policy is not None else 0,
    )
    return Proposals(
        cards=cards,
        policy=policy,
        counted=bool(cards) or has_counted_campaigns(db, owner=owner),
        working=working(db, owner=owner, now=now),
        late=check_is_late(db, owner=owner, now=now),
    )


__all__ = [
    "AdviceCard",
    "Proposals",
    "Summary",
    "advice_cards",
    "agent_summary",
    "has_counted_campaigns",
    "proposals",
]
