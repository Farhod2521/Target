"""The lead form a launch collects through: which, how deep, and how it ends."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

from metaads.specs import is_external
from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    ENDING_BODY_MAX,
    ENDING_BUTTON_MAX,
    ENDING_LABELS,
    ENDING_TITLE_MAX,
    FORM_DEPTH,
    FORM_DEPTH_LIMITS,
    FORM_DEPTH_WANTED,
    HIGHER_INTENT,
    LEAD_FORM_CHOICE,
    LEAD_FORM_ENDING,
    LEAD_FORM_NAME,
    LEAD_FORM_QUESTIONS,
    QUESTION_TYPES,
    DraftSection,
    FormDepth,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.campaign_type import campaign_type_locked
from app.modules.ads.selectors.delivery_options import goal_builds_a_form
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.variants import launch_variants, post_caption_of
from app.modules.businesses.models import Business
from core.leads.ending import (
    DEFAULT_BUTTON_TEXT,
    ENDING_CALL,
    ENDING_KINDS,
    ENDING_NONE,
    ENDING_TELEGRAM,
    ENDING_WEBSITE,
    EndingLine,
    FormEnding,
    ai_ending_kind,
    ending_from_answer,
    line_of,
)

ADVERT_TEXT_MAX: Final = 1200
PENDING_MINUTES: Final = 3
_RULES: Final[dict[str, str]] = {
    FormDepth.SHORT: (
        "**Many leads, each one cheap.** Two or three questions in all, the name "
        "and the phone number among them - never more than three. Name and phone "
        "are almost always enough, and every extra question costs leads. Add a "
        "third only when its answer changes how the business follows up - which "
        "service, which branch - and give it 2 to 5 answers to pick from."
    ),
    FormDepth.DEEP: (
        "**Fewer leads, each one worth ringing.** Four to seven questions in all, "
        "the name and the phone number among them - never more than seven. After "
        "those, ask what tells the business whether this person is ready to buy: "
        "which service or product they want, from what the adverts and the offer "
        "name; how soon they need it; which price range suits them, only when the "
        "adverts or the offer give prices; and the city or branch when the business "
        "has more than one. Each as a choice of 2 to 5 answers. At most one question "
        "answered in their own words, and only as the last one."
    ),
}


# -- the ending ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EndingChoice:
    ending: FormEnding
    by_owner: bool

    @property
    def line(self) -> EndingLine:
        return line_of(self.ending)

    @property
    def source(self) -> str:
        return "owner" if self.by_owner else "ai"


def default_title(business: Business) -> str:
    title = f"{business.name}: tez orada siz bilan bog'lanamiz."
    if len(title) <= ENDING_TITLE_MAX:
        return title
    return "Tez orada siz bilan bog'lanamiz."


def stored_ending(*, launch: CampaignLaunch) -> FormEnding | None:
    return ending_from_answer(launch.answers.get(LEAD_FORM_ENDING))


def ai_ending(*, business: Business) -> FormEnding:
    """The rule's ending for this business, with what it needs behind it."""
    category = "" if business.custom_category_id else business.category
    kind = ai_ending_kind(category=category)
    if kind == ENDING_WEBSITE:
        target = business.website if is_external(business.website) else ""
    elif kind == ENDING_CALL:
        target = business.contact_phone
    else:
        target = ""
    if kind != ENDING_NONE and not target:
        return FormEnding(kind=ENDING_NONE)
    return FormEnding(kind=kind, target=target)


def effective_ending(*, launch: CampaignLaunch, business: Business) -> EndingChoice:
    stored = stored_ending(launch=launch)
    if stored is not None:
        return EndingChoice(ending=stored, by_owner=True)
    return EndingChoice(ending=ai_ending(business=business), by_owner=False)


def ending_fields(*, ending: FormEnding | None, business: Business) -> dict[str, Any]:
    """What the ending controls open on."""
    chosen = ending or FormEnding(kind=ENDING_NONE)
    target = chosen.target
    return {
        "kind": chosen.kind if ending is not None else "",
        "website": target
        if chosen.kind == ENDING_WEBSITE
        else (business.website if is_external(business.website) else ""),
        "telegram": f"@{target}" if chosen.kind == ENDING_TELEGRAM else "",
        "phone": target if chosen.kind == ENDING_CALL else business.contact_phone,
        "button": chosen.button_text,
        "title": chosen.title or default_title(business),
        "body": chosen.body,
        **ending_chrome(),
    }


def ending_chrome() -> dict[str, Any]:
    return {
        "kinds": [(kind, str(ENDING_LABELS[kind])) for kind in ENDING_KINDS],
        "defaults": dict(DEFAULT_BUTTON_TEXT),
        "title_max": ENDING_TITLE_MAX,
        "body_max": ENDING_BODY_MAX,
        "button_max": ENDING_BUTTON_MAX,
    }


# -- the depth -------------------------------------------------------------------------


def form_depth(*, launch: CampaignLaunch) -> str:
    stored = str(launch.answers.get(FORM_DEPTH) or "")
    return stored if stored in FORM_DEPTH_LIMITS else FormDepth.SHORT


def wanted_depth(*, launch: CampaignLaunch) -> str:
    wanted = str(launch.answers.get(FORM_DEPTH_WANTED) or "")
    return wanted if wanted in FORM_DEPTH_LIMITS else form_depth(launch=launch)


def question_limit(*, launch: CampaignLaunch) -> int:
    return FORM_DEPTH_LIMITS[form_depth(launch=launch)]


def offers_form_depth(db: Session, *, launch: CampaignLaunch) -> bool:
    return goal_builds_a_form(db, launch=launch)


def depth_changeable(db: Session, *, launch: CampaignLaunch) -> bool:
    return offers_form_depth(db, launch=launch) and not campaign_type_locked(
        launch=launch
    )


DepthState = Literal["current", "ready", "pending", "failed", "missing"]


@dataclass(frozen=True, slots=True)
class DepthBlock:
    depth: str
    state: DepthState
    questions: tuple[dict[str, Any], ...] = ()
    custom_kinds: tuple[str, ...] = ()

    @property
    def limit(self) -> int:
        return FORM_DEPTH_LIMITS.get(self.depth, 0)


@dataclass(frozen=True, slots=True)
class FormDepthChoice:
    chosen: str
    limits: dict[str, int]
    locked: bool
    intent: bool
    short_form: str
    blocks: dict[str, DepthBlock]


def variant_pending(kept: dict[str, Any], *, now: datetime, minutes: int) -> bool:
    raw = kept.get("pending_at")
    if not raw:
        return False
    try:
        since = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    return now - since < timedelta(minutes=minutes)


def depth_block(*, launch: CampaignLaunch, depth: str, now: datetime) -> DepthBlock:
    if depth == form_depth(launch=launch):
        return DepthBlock(depth=depth, state="current")
    kept = draft_field.form_variants(launch.draft).get(depth) or {}
    if "questions" in kept:
        return _ready_block(depth=depth, questions=kept["questions"])
    if variant_pending(kept, now=now, minutes=PENDING_MINUTES):
        return DepthBlock(depth=depth, state="pending")
    if kept.get("failed"):
        return DepthBlock(depth=depth, state="failed")
    return DepthBlock(depth=depth, state="missing")


def polled_block(*, launch: CampaignLaunch, depth: str, now: datetime) -> DepthBlock:
    block = depth_block(launch=launch, depth=depth, now=now)
    if block.state != "current":
        return block
    return _ready_block(
        depth=depth,
        questions=draft_field.chosen(launch.draft, DraftSection.FORM) or [],
    )


def _ready_block(*, depth: str, questions: list[Any]) -> DepthBlock:
    rows = tuple(item for item in questions if isinstance(item, dict))
    return DepthBlock(
        depth=depth,
        state="ready",
        questions=rows,
        custom_kinds=tuple(
            str(item.get("kind", ""))
            for item in rows
            if str(item.get("kind", "")) not in QUESTION_TYPES
        ),
    )


def form_depth_choice(
    db: Session, *, launch: CampaignLaunch, now: datetime
) -> FormDepthChoice | None:
    if not offers_form_depth(db, launch=launch):
        return None
    current = form_depth(launch=launch)
    chosen = wanted_depth(launch=launch)
    short = draft_field.form_variants(launch.draft).get(FormDepth.SHORT) or {}
    return FormDepthChoice(
        chosen=chosen,
        limits=dict(FORM_DEPTH_LIMITS),
        locked=campaign_type_locked(launch=launch),
        intent=bool(launch.answers.get(HIGHER_INTENT))
        if chosen == current
        else chosen == FormDepth.DEEP,
        short_form=launch.lead_form_external_id
        if current == FormDepth.SHORT
        else str(short.get("lead_form") or ""),
        blocks={
            depth: depth_block(launch=launch, depth=depth, now=now)
            for depth in FormDepth.values
        },
    )


def kept_questions(*, launch: CampaignLaunch) -> list[dict[str, Any]]:
    return [
        item
        for kept in draft_field.form_variants(launch.draft).values()
        for item in kept.get("questions") or []
        if isinstance(item, dict)
    ]


def form_rule_for(*, depth: str) -> str:
    return _RULES.get(depth, _RULES[FormDepth.SHORT])


def advert_words(db: Session, *, launch: CampaignLaunch) -> str:
    """Every advert's own text, numbered, as the model reads it."""
    blocks: list[str] = []
    for index, variant in enumerate(launch_variants(db, launch=launch), start=1):
        parts = [
            _clipped(text)
            for text in (
                post_caption_of(variant) or "",
                variant.brief,
                variant.headline,
                variant.primary_text,
            )
            if text and text.strip()
        ]
        if parts:
            blocks.append(f"{index}. " + "\n   ".join(dict.fromkeys(parts)))
    if not blocks:
        return "None yet - read the offer above instead."
    return "\n".join(blocks)


def current_questions(*, launch: CampaignLaunch) -> str:
    chosen = draft_field.chosen(launch.draft, DraftSection.FORM) or []
    rows = [
        {
            "kind": str(item.get("kind", "")),
            "label": str(item.get("label", "")),
            "options": list(item.get("options") or []),
        }
        for item in chosen
        if isinstance(item, dict)
    ]
    if not rows:
        return "None."
    return json.dumps(rows, ensure_ascii=False, indent=2)


def form_variables(
    db: Session, *, launch: CampaignLaunch, depth: str
) -> dict[str, str]:
    return {
        "form_rule": form_rule_for(depth=depth),
        "advert_words": advert_words(db, launch=launch),
        "current_questions": current_questions(launch=launch),
    }


def _clipped(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= ADVERT_TEXT_MAX else text[:ADVERT_TEXT_MAX] + "…"


# -- the choice ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FormChoice:
    by_owner: bool
    external_id: str
    name: str
    questions: tuple[str, ...]
    is_missing: bool
    ending: EndingLine | None = None
    depth: str = ""


def form_choice(db: Session, *, launch: CampaignLaunch) -> FormChoice:
    """Which form this launch collects through, as far as the owner said."""
    from app.modules.leads.selectors.reads import form_option

    answered = launch.answers.get(LEAD_FORM_CHOICE) == draft_field.BY_OWNER
    picked = launch.lead_form_external_id
    if not picked:
        stored = launch.answers.get(LEAD_FORM_QUESTIONS) or []
        ending = stored_ending(launch=launch)
        return FormChoice(
            by_owner=answered,
            external_id="",
            name=str(launch.answers.get(LEAD_FORM_NAME) or ""),
            questions=tuple(
                str(item.get("label", "")) for item in stored if isinstance(item, dict)
            ),
            is_missing=False,
            ending=line_of(ending) if ending is not None else None,
            depth=wanted_depth(launch=launch),
        )
    page = launch_page(db, launch=launch)
    found = (
        form_option(db, owner=launch.owner, page=page, external_id=picked)
        if page is not None
        else None
    )
    if found is None:
        return FormChoice(
            by_owner=answered,
            external_id=picked,
            name="",
            questions=(),
            is_missing=True,
        )
    return FormChoice(
        by_owner=answered,
        external_id=picked,
        name=found.name,
        questions=found.questions,
        is_missing=False,
        ending=found.ending,
    )
