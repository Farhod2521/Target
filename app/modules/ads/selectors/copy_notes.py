"""What the owner wrote, where the button goes, and what is wrong with the words."""

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import DraftSection
from app.modules.ads.models import CampaignLaunch, LaunchCreative
from app.modules.ads.selectors.goals import goal_preset
from app.modules.ads.selectors.variants import post_caption, variants_needing_words
from app.modules.businesses.models import Business
from core.agent.copy_check import AdWords, CopyFinding, check_against_offer, check_words

NO_BUTTON: Final = "nothing"


def destination_phone(*, launch: CampaignLaunch, business: Business) -> str:
    """The number this campaign's ad dials, if it dials one."""
    answered = str(launch.answers.get("phone_number") or "").strip()
    return answered or str(business.contact_phone or "").strip()


def offer_text(db: Session, *, launch: CampaignLaunch, business: Business) -> str:
    """What the owner said they sell, from the first of three places that has it."""
    return (
        str(launch.answers.get("offer_text", ""))
        or post_caption(db, launch=launch)
        or str(business.offer_text or "")
    )


@dataclass(frozen=True, slots=True)
class AdvertFacts:
    offer: str
    brief: str = ""

    @property
    def joined(self) -> str:
        return "\n".join(part for part in (self.offer, self.brief) if part)


def facts_by_advert(
    db: Session, *, launch: CampaignLaunch, business: Business
) -> list[AdvertFacts]:
    offer = offer_text(db, launch=launch, business=business)
    return [
        AdvertFacts(offer=offer, brief=row.brief.strip())
        for row in variants_needing_words(db, launch=launch)
    ]


def button_action(db: Session, *, launch: CampaignLaunch) -> str:
    preset = goal_preset(db, launch=launch)
    return str(preset.sends_to) if preset is not None else NO_BUTTON


def copy_notes(
    db: Session, *, launch: CampaignLaunch, business: Business, sends_to: str
) -> dict[int, tuple[CopyFinding, ...]]:
    """What is wrong with each advert's words, by position. Fine ones are absent."""
    rows = variants_needing_words(db, launch=launch)
    proposed = _proposals(launch)
    facts = facts_by_advert(db, launch=launch, business=business)
    notes: dict[int, tuple[CopyFinding, ...]] = {}
    for index, row in enumerate(rows):
        words = _words_of(row)
        if proposed and _same(words, proposed[min(index, len(proposed) - 1)]):
            found = check_against_offer(
                words=words, facts=facts[index].joined, sends_to=sends_to or NO_BUTTON
            )
        else:
            found = check_words(words=words)
        if found:
            notes[row.position] = found
    return notes


def missing_copy(db: Session, *, launch: CampaignLaunch) -> bool:
    return any(
        not row.primary_text.strip()
        for row in variants_needing_words(db, launch=launch)
    )


def _proposals(launch: CampaignLaunch) -> list[dict[str, Any]]:
    value = draft_field.proposal(launch.draft or {}, DraftSection.CREATIVE)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _words_of(row: LaunchCreative) -> AdWords:
    return AdWords(
        primary_text=row.primary_text,
        headline=row.headline,
        description=row.description,
    )


def _same(words: AdWords, item: dict[str, Any]) -> bool:
    return (
        words.primary_text.strip() == str(item.get("primary_text", "")).strip()
        and words.headline.strip() == str(item.get("headline", "")).strip()
        and words.description.strip() == str(item.get("description", "")).strip()
    )
