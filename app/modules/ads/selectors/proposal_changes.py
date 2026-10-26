"""What the owner changed on the proposal, in the card's words."""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ads import audiences as audience_field
from app.modules.ads import draft as draft_field
from app.modules.ads import edits
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    ATTRIBUTION,
    CALL_TO_ACTION,
    FREQUENCY_CAP,
    HIGHER_INTENT,
    LEAD_FORM_ENDING,
    PIXEL_ID,
    DraftSection,
    PlacementMode,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.variants import launch_variants
from app.modules.ads.summaries import audience_summary
from core.targeting import DEFAULT_TARGETING_MODE

AUDIENCE = "audience"
INTERESTS = "interests"
TRAITS = "traits"
CREATIVE = "creative"
FORM = "form"
QUESTIONS = "questions"
ADVANCED = "advanced"
ORDER = (AUDIENCE, INTERESTS, TRAITS, CREATIVE, FORM, QUESTIONS, ADVANCED)
ADVANCED_ANSWERS = (PIXEL_ID, CALL_TO_ACTION, ATTRIBUTION, FREQUENCY_CAP, HIGHER_INTENT)
MAX_NAMED = 2


@dataclass(frozen=True, slots=True)
class ProposalChange:
    label: str
    before: str
    after: str


def proposal_snapshot(db: Session, *, launch: CampaignLaunch) -> edits.Snapshot:
    """Every item the edit layer can change, as readable strings."""
    draft = launch.draft or {}
    return {
        AUDIENCE: _audience(draft),
        INTERESTS: _labels(draft_field.chosen(draft, DraftSection.INTERESTS)),
        TRAITS: _labels(draft_field.chosen(draft, DraftSection.TRAITS)),
        CREATIVE: [
            "\n".join((row.primary_text, row.headline, row.description))
            for row in launch_variants(db, launch=launch)
        ],
        FORM: [
            launch.lead_form_external_id,
            _stable(launch.answers.get(LEAD_FORM_ENDING)),
        ],
        QUESTIONS: _labels(draft_field.chosen(draft, DraftSection.FORM)),
        ADVANCED: [_stable(_advanced(launch))],
    }


def proposal_changes(db: Session, *, launch: CampaignLaunch) -> list[ProposalChange]:
    """The owner's changes still standing, in the card's order."""
    kept = edits.baselines(launch.draft or {})
    if not kept:
        return []
    now = proposal_snapshot(db, launch=launch)
    return [
        _line(key, before=kept[key], after=now.get(key, []))
        for key in ORDER
        if key in kept and not same_value(key, kept[key], now.get(key, []))
    ]


def same_value(key: str, first: list[str], second: list[str]) -> bool:
    if key != AUDIENCE:
        return first == second
    return _audience_words(first) == _audience_words(second) and _own(first) == _own(
        second
    )


def _line(key: str, *, before: list[str], after: list[str]) -> ProposalChange:
    if key == AUDIENCE:
        before, after = _audience_words(before), _audience_words(after)
        moved = [
            i for i, value in enumerate(after) if i >= len(before) or before[i] != value
        ]
        if not moved:
            return ProposalChange(label="Auditoriya", before="", after="O'zgartirildi")
        return ProposalChange(
            label="Auditoriya",
            before=" · ".join(before[i] for i in moved if i < len(before)),
            after=" · ".join(after[i] for i in moved),
        )
    if key in (INTERESTS, TRAITS, QUESTIONS):
        labels = {
            INTERESTS: "Qiziqishlar",
            TRAITS: "Holat va odatlar",
            QUESTIONS: "Forma savollari",
        }
        return ProposalChange(
            label=labels[key], before="", after=_names_moved(before, after)
        )
    said = {
        CREATIVE: ("Reklama matni", "O'z matningiz yozildi"),
        FORM: ("Lid formasi", "O'zgartirildi"),
        ADVANCED: ("Kengaytirilgan sozlamalar", "O'zgartirildi"),
    }
    label, words = said[key]
    return ProposalChange(label=label, before="", after=words)


def _names_moved(before: list[str], after: list[str]) -> str:
    added = [name for name in after if name not in before]
    removed = [name for name in before if name not in after]
    parts = []
    if added:
        parts.append(
            _said(added, one="«%(names)s» qo'shildi", many="%(n)s ta qo'shildi")
        )
    if removed:
        parts.append(
            _said(
                removed,
                one="«%(names)s» olib tashlandi",
                many="%(n)s ta olib tashlandi",
            )
        )
    return ", ".join(parts) or "Tartibi o'zgardi"


def _said(names: list[str], *, one: str, many: str) -> str:
    if len(names) <= MAX_NAMED:
        return one % {"names": "», «".join(names)}
    return many % {"n": len(names)}


def _audience(draft: dict[str, Any]) -> list[str]:
    audience = draft_field.chosen(draft, DraftSection.AUDIENCE) or {}
    kept = {key: value for key, value in audience.items() if key != "reason"}
    return [_stable(kept)]


def _stored_audience(kept: list[str]) -> dict[str, Any]:
    try:
        audience = json.loads(kept[0]) if kept else {}
    except ValueError:
        return {}
    return audience if isinstance(audience, dict) else {}


def _own(kept: list[str]) -> dict[str, str]:
    return audience_field.roles(_stored_audience(kept))


def _audience_words(kept: list[str]) -> list[str]:
    audience = _stored_audience(kept)
    card = audience_summary(
        audience=audience,
        geo=geo_field.stored(audience),
        places=geo_field.known_places(audience),
        mode=audience.get("targeting_mode") or DEFAULT_TARGETING_MODE,
        placement=audience.get("placement_mode") or PlacementMode.AUTOMATIC,
    )
    return [
        str(card.where),
        str(card.ages),
        str(card.genders),
        str(card.mode),
        str(card.placement),
    ]


def _labels(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [
        str(item.get("label") or item.get("query") or "")
        for item in items
        if isinstance(item, dict)
    ]


def _advanced(launch: CampaignLaunch) -> dict[str, Any]:
    draft = launch.draft or {}
    return {
        **{key: launch.answers.get(key) for key in ADVANCED_ANSWERS},
        "campaign_type": draft_field.campaign_type(draft),
        "conversion_event": draft_field.conversion_event(draft),
        "url_tags": draft_field.url_tags(draft),
        "end_date": launch.end_date,
        "total_cap": launch.total_cap_minor,
        "cost_cap": launch.max_result_cost_minor,
    }


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)
