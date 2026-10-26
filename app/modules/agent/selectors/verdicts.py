"""What the agent thinks of each campaign, for the row that lists it."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.agent.constants import RULE_LABELS, RULE_TONES, SuggestionKind
from app.modules.agent.models import AgentSuggestion
from app.modules.agent.selectors.suggestions import decided, waiting

OFFER = "offer"
LEARNING = "learning"
LAST = "last"
FLAT = "flat"


@dataclass(frozen=True, slots=True)
class Verdict:
    """One campaign's line from the agent, ready to draw."""

    campaign_id: str
    kind: str
    tone: str
    label: Any
    reason: str
    suggestion_id: str = ""
    action_label: Any = ""
    decided_at: datetime | None = None
    opens_words: bool = False


def campaign_verdicts(
    db: Session, *, owner: User, campaigns: list[Campaign], now: datetime
) -> tuple[Verdict, ...]:
    """One line per campaign the agent has something to say about."""
    if not campaigns:
        return ()
    keys = [str(campaign.id) for campaign in campaigns]
    found = _loudest(db, owner=owner, wanted=set(keys), now=now)
    return tuple(found.get(key) or _silent(campaign_id=key) for key in keys)


def _loudest(
    db: Session, *, owner: User, wanted: set[str], now: datetime
) -> dict[str, Verdict]:
    """The one thing worth saying about each campaign, in order of loudness."""
    by_object = _campaign_by_object(db, owner=owner)
    found: dict[str, Verdict] = {}
    for row in waiting(db, owner=owner, now=now):
        campaign_id = by_object.get(row.target_external_id, "")
        if campaign_id in wanted and campaign_id not in found:
            found[campaign_id] = _offer(row=row, campaign_id=campaign_id)
    for campaign_id in _learning_campaigns(db, owner=owner):
        if campaign_id in wanted and campaign_id not in found:
            found[campaign_id] = Verdict(
                campaign_id=campaign_id, kind=LEARNING, tone=FLAT, label="", reason=""
            )
    for row in decided(db, owner=owner):
        campaign_id = by_object.get(row.target_external_id, "")
        if campaign_id in wanted and campaign_id not in found:
            found[campaign_id] = _last(row=row, campaign_id=campaign_id)
    return found


def _silent(*, campaign_id: str) -> Verdict:
    """A block with nothing in it, for a campaign the agent has not judged."""
    return Verdict(campaign_id=campaign_id, kind="", tone=FLAT, label="", reason="")


def _offer(*, row: AgentSuggestion, campaign_id: str) -> Verdict:
    return Verdict(
        campaign_id=campaign_id,
        kind=OFFER,
        tone=RULE_TONES.get(row.rule, FLAT),
        label=RULE_LABELS.get(row.rule, ""),
        reason=row.reason,
        suggestion_id=str(row.id),
        action_label=SuggestionKind(row.kind).label,
        opens_words=row.kind == SuggestionKind.NEW_AD,
    )


def _last(*, row: AgentSuggestion, campaign_id: str) -> Verdict:
    """What was decided about this campaign, for a row with nothing open."""
    return Verdict(
        campaign_id=campaign_id,
        kind=LAST,
        tone=FLAT,
        label=RULE_LABELS.get(row.rule, ""),
        reason=row.reason,
        decided_at=row.decided_at,
    )


def _campaign_by_object(db: Session, *, owner: User) -> dict[str, str]:
    """``{provider id: row pk}`` for every ad set and advert we mirror."""
    found = {
        external_id: str(campaign_id)
        for external_id, campaign_id in db.execute(
            select(AdSet.external_id, AdSet.campaign_id).where(
                AdSet.owner_id == owner.id
            )
        )
    }
    found |= {
        external_id: str(campaign_id)
        for external_id, campaign_id in db.execute(
            select(Ad.external_id, AdSet.campaign_id)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .where(Ad.owner_id == owner.id)
        )
    }
    return found


def _learning_campaigns(db: Session, *, owner: User) -> set[str]:
    """Campaigns whose provider is still working out who to show them to."""
    return {
        str(campaign_id)
        for campaign_id in db.scalars(
            select(AdSet.campaign_id).where(
                AdSet.owner_id == owner.id, AdSet.is_learning.is_(True)
            )
        )
    }


def campaign_of(db: Session, *, owner: User, suggestion: AgentSuggestion) -> str:
    """Which campaign row one proposal belongs to, or an empty string."""
    level = suggestion.target_level
    found: Any = None
    if level == ManagedLevel.ADSET:
        found = db.scalar(
            select(AdSet.campaign_id).where(
                AdSet.owner_id == owner.id,
                AdSet.external_id == suggestion.target_external_id,
            )
        )
    elif level == ManagedLevel.AD:
        found = db.scalar(
            select(AdSet.campaign_id)
            .join(Ad, Ad.adset_id == AdSet.id)
            .where(
                Ad.owner_id == owner.id, Ad.external_id == suggestion.target_external_id
            )
        )
    return str(found) if found else ""


__all__ = ["LAST", "LEARNING", "OFFER", "Verdict", "campaign_of", "campaign_verdicts"]
