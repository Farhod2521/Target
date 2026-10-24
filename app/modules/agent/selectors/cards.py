"""One proposal, as the screen needs it: what we would change, why, what we expect, and when we check."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent import aftermath, aims, causes
from app.modules.agent.aftermath import Comparison
from app.modules.agent.constants import (
    ACTION_LABELS,
    AUTOMATION_NOTES,
    NARROWING_LABELS,
    NEW_PICTURE_NAMED,
    NO_AUDIENCE_LEFT,
    OPEN_STATUSES,
    REASON_ON_EARLIER_FIGURES,
    RECENT_DECIDED,
    RULE_LABELS,
    STALE_LABELS,
    WIDENING_LABELS,
    SuggestionKind,
    SuggestionOutcome,
    SuggestionStatus,
)
from app.modules.agent.figures import readable
from app.modules.agent.models import AgentSuggestion
from app.modules.agent.selectors.pictures import CardPicture, card_pictures
from app.modules.agent.selectors.suggestions import (
    decided,
    recently_assessed,
    unanswered,
    waiting,
)
from app.modules.integrations.models import AdAccount
from core.agent.rules import PROVIDER_ADVICE


@dataclass(frozen=True, slots=True)
class Card:
    """One suggestion, ready to draw."""

    pk: str
    kind: str
    kind_label: Any
    action_label: Any
    rule_label: Any
    target_name: str
    reason: str
    figures: tuple[tuple[Any, str], ...]
    note: Any
    expectation: Any
    review_note: Any
    review_at: datetime | None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    status: str
    status_label: Any
    stale_label: Any
    reason_dated: bool = False
    outcome: str = ""
    outcome_label: Any = ""
    after: tuple[tuple[Any, str], ...] = ()
    is_unanswered: bool = False
    landed: bool | None = None
    cause_label: Any = ""
    cause_line: str = ""
    result_line: str = ""
    expectation_figure: str = ""
    comparison: Comparison | None = None
    picture: CardPicture | None = None
    words: tuple[str, str, str] = ("", "", "")

    @property
    def cursor(self) -> str:
        """Where a history page ends, for the next one to carry."""
        moment = self.decided_at or self.created_at
        return moment.isoformat()


def pending_cards(
    db: Session,
    *,
    owner: User,
    now: datetime,
    cooldown_hours: int = 0,
    scope: PageScope | None = None,
) -> list[Card]:
    """Everything still open, dearest first - and the fresh ones first of all."""
    return _cards(
        db,
        owner=owner,
        rows=waiting(db, owner=owner, now=now, scope=scope)
        + unanswered(db, owner=owner, now=now, scope=scope),
        cooldown_hours=cooldown_hours,
        now=now,
    )


def history_cards(
    db: Session,
    *,
    owner: User,
    limit: int = RECENT_DECIDED,
    before: datetime | None = None,
    scope: PageScope | None = None,
) -> list[Card]:
    """What is no longer open, newest first. One page of it."""
    return _cards(
        db,
        owner=owner,
        rows=decided(db, owner=owner, limit=limit, before=before, scope=scope),
    )


def outcome_cards(
    db: Session, *, owner: User, since: datetime, scope: PageScope | None = None
) -> list[Card]:
    """The handful of verdicts fresh enough to be news."""
    return _cards(
        db,
        owner=owner,
        rows=recently_assessed(db, owner=owner, since=since, scope=scope),
    )


def card_for(db: Session, *, owner: User, suggestion: AgentSuggestion) -> Card:
    """One proposal, for a reader that already has the row."""
    return _cards(db, owner=owner, rows=[suggestion])[0]


def _cards(
    db: Session,
    *,
    owner: User,
    rows: list[AgentSuggestion],
    cooldown_hours: int = 0,
    now: datetime | None = None,
) -> list[Card]:
    """Rows joined to their object names and to the account's currency."""
    from app.modules.integrations.selectors import active_ad_account

    if not rows:
        return []
    account = active_ad_account(db, owner=owner)
    fallback = account.currency if account is not None else ""
    names = _names(db, owner=owner, rows=rows)
    pictures = card_pictures(db, owner=owner, rows=rows)
    return [
        replace(
            _card(
                row=row,
                names=names,
                currency=_currency(row, fallback=fallback),
                cooldown_hours=cooldown_hours,
                now=now,
            ),
            picture=pictures.get(str((row.payload or {}).get("asset_id", ""))),
            words=_words(row),
        )
        for row in rows
    ]


def _currency(row: AgentSuggestion, *, fallback: str) -> str:
    return str((row.evidence or {}).get("currency") or fallback)


def _names(db: Session, *, owner: User, rows: list[AgentSuggestion]) -> dict[str, str]:
    """``{provider id: name}`` for every object these rows point at."""
    wanted: dict[str, set[str]] = {}
    for row in rows:
        wanted.setdefault(row.target_level, set()).add(row.target_external_id)

    found: dict[str, str] = {}
    if wanted.get(ManagedLevel.ADSET):
        found |= dict(
            db.execute(
                select(AdSet.external_id, AdSet.name)
                .join(Campaign, Campaign.id == AdSet.campaign_id)
                .join(AdAccount, AdAccount.id == Campaign.ad_account_id)
                .where(
                    AdSet.owner_id == owner.id,
                    AdAccount.is_active.is_(True),
                    AdSet.external_id.in_(wanted[ManagedLevel.ADSET]),
                )
            ).all()
        )
    if wanted.get(ManagedLevel.AD):
        found |= dict(
            db.execute(
                select(Ad.external_id, Ad.name)
                .join(AdSet, AdSet.id == Ad.adset_id)
                .join(Campaign, Campaign.id == AdSet.campaign_id)
                .join(AdAccount, AdAccount.id == Campaign.ad_account_id)
                .where(
                    Ad.owner_id == owner.id,
                    AdAccount.is_active.is_(True),
                    Ad.external_id.in_(wanted[ManagedLevel.AD]),
                )
            ).all()
        )
    return found


def _card(
    *,
    row: AgentSuggestion,
    names: dict[str, str],
    currency: str,
    cooldown_hours: int,
    now: datetime | None = None,
) -> Card:
    return Card(
        pk=str(row.id),
        kind=row.kind,
        kind_label=SuggestionKind(row.kind).label,
        action_label=ACTION_LABELS.get(row.kind, ""),
        rule_label=RULE_LABELS.get(row.rule, row.rule),
        target_name=names.get(row.target_external_id) or row.target_external_id,
        reason=row.reason,
        figures=tuple(readable(row.evidence, currency=currency)),
        note=_note(row),
        expectation=aims.expectation(rule=row.rule, evidence=_goal(row)),
        review_note=_review_note(row=row, cooldown_hours=cooldown_hours),
        review_at=None if row.outcome else row.review_at,
        created_at=row.created_at,
        expires_at=row.expires_at,
        decided_at=row.decided_at,
        status=row.status,
        status_label=SuggestionStatus(row.status).label,
        stale_label=STALE_LABELS.get(row.stale_reason, ""),
        reason_dated=bool((row.evidence or {}).get(REASON_ON_EARLIER_FIGURES)),
        is_unanswered=_is_unanswered(row=row, now=now),
        landed=_landed(row),
        outcome=row.outcome,
        outcome_label=SuggestionOutcome(row.outcome).label if row.outcome else "",
        after=tuple(readable(row.outcome_figures, currency=currency)),
        cause_label=causes.cause_label(row.cause),
        cause_line=causes.cause_line(row.diagnosis, currency=currency),
        result_line=aims.result_line(_goal(row), currency=currency),
        expectation_figure=aims.expected_figure(
            rule=row.rule, diagnosis=row.diagnosis, currency=currency
        ),
        comparison=aftermath.comparison(
            rule=row.rule,
            evidence=row.evidence,
            after=row.outcome_figures,
            currency=currency,
        )
        if row.outcome
        else None,
    )


def _goal(row: AgentSuggestion) -> dict[str, Any]:
    return aims.goal_of(evidence=row.evidence or {}, diagnosis=row.diagnosis or {})


def _words(row: AgentSuggestion) -> tuple[str, str, str]:
    """The proposed words of a new advert, or three blanks."""
    if row.kind != SuggestionKind.NEW_AD:
        return ("", "", "")
    payload = row.payload or {}
    return (
        str(payload.get("headline", "")),
        str(payload.get("message", "")),
        str(payload.get("description", "")),
    )


def _landed(row: AgentSuggestion) -> bool | None:
    """What the worker saw when it read the object back after the write."""
    log = row.action_log
    if log is None:
        return None
    found = (log.result_payload or {}).get("landed")
    return found if isinstance(found, bool) else None


def _is_unanswered(*, row: AgentSuggestion, now: datetime | None) -> bool:
    if now is None or row.status not in OPEN_STATUSES:
        return False
    return row.status == SuggestionStatus.UNANSWERED or row.expires_at <= now


def _review_note(*, row: AgentSuggestion, cooldown_hours: int) -> Any:
    """The conditional, for a proposal nobody has answered yet."""
    if row.outcome or row.review_at is not None:
        return ""
    days = max(1, round(cooldown_hours / 24)) if cooldown_hours else 0
    if not days:
        return ""
    return "Tasdiqlasangiz, %(days)d kundan keyin natijani tekshiramiz." % {
        "days": days
    }


def _note(row: AgentSuggestion) -> Any:
    """The extra line a change needs when its name does not carry it."""
    evidence = row.evidence or {}
    if row.kind == SuggestionKind.NEW_PICTURE:
        name = str(evidence.get("picture_name") or "").strip()
        return NEW_PICTURE_NAMED % {"name": name} if name else ""
    if row.kind == SuggestionKind.DROP_AUDIENCE:
        return NO_AUDIENCE_LEFT if evidence.get("kept_audiences") == 0 else ""

    step = str((row.payload or {}).get("step", ""))
    if row.kind == SuggestionKind.SWAP_TARGETING:
        if row.rule == PROVIDER_ADVICE:
            return _automation_note(row)
        return WIDENING_LABELS.get(step, "")
    if row.kind == SuggestionKind.NARROW_TARGETING:
        return NARROWING_LABELS.get(step, "")
    return ""


def _automation_note(row: AgentSuggestion) -> Any:
    """What the provider's mode would not accept beside the switch."""
    moved = (row.evidence or {}).get("changed") or ()
    lines = [AUTOMATION_NOTES[field] for field in moved if field in AUTOMATION_NOTES]
    return ". ".join(str(line) for line in lines)


__all__ = ["Card", "card_for", "history_cards", "outcome_cards", "pending_cards"]
