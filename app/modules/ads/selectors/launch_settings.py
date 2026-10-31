"""What one launch was set to, and who decided each part of it.

The office reads it beside the figures. Everything here is what this product
stored when the launch was prepared, so nothing asks the provider anything.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.common.catalogs import COUNTRIES
from app.common.presets import goal_labels
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    ATTRIBUTION,
    ATTRIBUTION_LABELS,
    BUTTON_LABELS,
    CALL_TO_ACTION,
    CAMPAIGN_TYPE_LABELS,
    FREQUENCY_CAP,
    LEAD_FORM_QUESTIONS,
    MEDIA_KIND_LABELS,
    PLACEMENT_MODE_LABELS,
    TARGETING_MODE_LABELS,
    DraftSection,
    LaunchStep,
    MediaKind,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative, MediaAsset
from app.modules.ads.selectors.campaign_type import (
    campaign_type_source,
    effective_campaign_type,
)
from app.modules.ads.selectors.conversion_event import (
    chosen_conversion_event,
    conversion_event_source,
)
from app.modules.ads.selectors.tracking import chosen_url_tags, effective_button
from core.targeting.spelled import AudienceWords, Place, spell

PLATFORM_LABELS: dict[str, str] = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "messenger": "Messenger",
    "audience_network": "Audience Network",
    "threads": "Threads",
    "whatsapp": "WhatsApp",
}
POSITION_LABELS: dict[str, str] = {
    "feed": "lenta",
    "stream": "lenta",
    "story": "Stories",
    "reels": "Reels",
    "profile_feed": "profil lentasi",
    "profile_reels": "profil Reels",
    "ig_search": "qidiruv",
    "explore": "Explore",
    "explore_home": "Explore",
    "video_feeds": "video lenta",
    "marketplace": "Marketplace",
    "search": "qidiruv",
}
BY_LABELS: Final[dict[str, str]] = {
    draft_field.BY_AI: "AI",
    draft_field.BY_OWNER: "Mijoz",
}
UNKNOWN_BY: Final = "Noma'lum"
READY_FORM: Final[dict[str, str]] = {
    draft_field.BY_AI: "AI tayyor formani tanladi",
    draft_field.BY_OWNER: "Mijoz tayyor formani tanladi",
}
NEW_FORM: Final[dict[str, str]] = {
    draft_field.BY_AI: "AI yangi forma yozdi",
    draft_field.BY_OWNER: "Mijoz savollarni o'zi yozdi",
}
UNKNOWN_FORM: Final = "Forma manbasi noma'lum"
_PIN: Final = "a pin at "
_COUNTRIES: Final = dict(COUNTRIES)


@dataclass(frozen=True, slots=True)
class AudienceLines:
    """One targeting spec, each part already in words a screen can print."""

    places: tuple[str, ...]
    excluded_places: tuple[str, ...]
    ages: str
    genders: str
    interests: tuple[tuple[str, ...], ...]
    excluded_interests: tuple[str, ...]
    placements: tuple[str, ...]
    devices: tuple[str, ...]
    own_lists: tuple[str, ...]
    excluded_lists: tuple[str, ...]
    is_automatic: bool


@dataclass(frozen=True, slots=True)
class Decision:
    """One part of the advert, and whether the AI or the customer settled it."""

    key: str
    label: str
    value: str
    by: str

    @property
    def by_label(self) -> str:
        return BY_LABELS.get(self.by, UNKNOWN_BY)


@dataclass(frozen=True, slots=True)
class LaunchAd:
    """One advert of a launch, as it was written."""

    id: UUID
    position: int
    name: str
    headline: str
    text: str
    description: str
    words_by: str
    picture: str
    is_video: bool
    video_url: str
    media_kind_label: str
    post_url: str

    @property
    def words_by_label(self) -> str:
        return BY_LABELS.get(self.words_by, UNKNOWN_BY)


@dataclass(frozen=True, slots=True)
class LaunchSettings:
    id: UUID
    goal: str
    goal_text: str
    offer_text: str
    link_url: str
    phone: str
    campaign_name: str
    created_at: datetime
    page: str
    currency: str
    daily_budget_minor: int | None
    daily_min_minor: int | None
    daily_max_minor: int | None
    total_cap_minor: int | None
    max_result_cost_minor: int | None
    start_date: date | None
    end_date: date | None
    audience_lower: int | None
    audience_upper: int | None
    audience: AudienceLines
    button: str
    conversion_event: str
    url_tags: str
    attribution: str
    frequency_cap: tuple[int, int] | None
    buys_qualified_leads: bool
    decisions: tuple[Decision, ...]
    ads: tuple[LaunchAd, ...]


def launch_settings(db: Session, *, launch: CampaignLaunch) -> LaunchSettings:
    stored = dict(launch.draft) if isinstance(launch.draft, dict) else {}
    answers = launch.answers or {}
    names = _place_names(stored)
    button = effective_button(db, launch=launch)
    return LaunchSettings(
        id=launch.id,
        goal=goal_labels().get(str(answers.get("goal") or ""), ""),
        goal_text=str(answers.get("goal_text") or ""),
        offer_text=str(answers.get("offer_text") or ""),
        link_url=str(answers.get("link_url") or ""),
        phone=str(answers.get("phone_number") or ""),
        campaign_name=launch.campaign_name,
        created_at=launch.created_at,
        page=launch.page.name if launch.page is not None else "",
        currency=launch.currency,
        daily_budget_minor=launch.daily_budget_minor,
        daily_min_minor=launch.daily_min_minor,
        daily_max_minor=launch.daily_max_minor,
        total_cap_minor=launch.total_cap_minor,
        max_result_cost_minor=launch.max_result_cost_minor,
        start_date=launch.start_date,
        end_date=launch.end_date,
        audience_lower=launch.audience_lower,
        audience_upper=launch.audience_upper,
        audience=audience_lines(launch.targeting, names=names),
        button=str(BUTTON_LABELS.get(button, button)) if button else "",
        conversion_event=chosen_conversion_event(launch=launch),
        url_tags=chosen_url_tags(launch=launch),
        attribution=_attribution(answers),
        frequency_cap=_frequency_cap(answers),
        buys_qualified_leads=launch.buy_qualified_leads,
        decisions=_decisions(launch, stored, button=button),
        ads=_ads(db, launch, stored),
    )


def audience_lines(
    spec: object, *, names: Mapping[str, str] | None = None
) -> AudienceLines:
    words = spell(spec)
    known = names or {}
    return AudienceLines(
        places=_places(words.places, known),
        excluded_places=_places(words.excluded_places, known),
        ages=_ages(words),
        genders=_genders(words.genders),
        interests=words.detailed,
        excluded_interests=words.excluded_detailed,
        placements=_placements(words),
        devices=words.devices,
        own_lists=words.own_lists,
        excluded_lists=words.excluded_lists,
        is_automatic=words.is_automatic,
    )


# -- who decided ---------------------------------------------------------------


def _decisions(
    launch: CampaignLaunch, stored: dict[str, Any], *, button: str
) -> tuple[Decision, ...]:
    answers = launch.answers or {}
    picked = draft_field.chosen(stored, DraftSection.AUDIENCE)
    audience = picked if isinstance(picked, dict) else {}
    mode = str(audience.get("targeting_mode") or "")
    placement = str(audience.get("placement_mode") or "")
    kind = effective_campaign_type(launch=launch)
    event = chosen_conversion_event(launch=launch)
    picks = _labels(draft_field.chosen(stored, DraftSection.INTERESTS))
    found = [
        Decision(
            key="campaign_type",
            label="Reklama turi",
            value=str(CAMPAIGN_TYPE_LABELS.get(kind, kind)),
            by=campaign_type_source(launch=launch),
        )
        if kind
        else None,
        Decision(
            key="conversion_event",
            label="Konversiya hodisasi",
            value=event,
            by=conversion_event_source(launch=launch),
        )
        if event
        else None,
        Decision(
            key="audience",
            label="Auditoriya usuli",
            value=str(TARGETING_MODE_LABELS.get(mode, mode)),
            by=draft_field.source(stored, draft_field.AUDIENCE_MODE)
            or _section_by(stored, DraftSection.AUDIENCE),
        )
        if mode
        else None,
        Decision(
            key="interests",
            label="Qiziqishlar",
            value=", ".join(sorted(picks)),
            by=_interests_by(stored, picks=picks),
        )
        if picks
        else None,
        Decision(
            key="placement",
            label="Joylashuv",
            value=str(PLACEMENT_MODE_LABELS.get(placement, placement)),
            by=draft_field.source(stored, draft_field.PLACEMENT_MODE),
        )
        if placement
        else None,
        _form_decision(launch, stored),
        Decision(
            key="button",
            label="Tugma",
            value=str(BUTTON_LABELS.get(button, button)),
            by=draft_field.BY_OWNER
            if answers.get(CALL_TO_ACTION)
            else draft_field.BY_AI,
        )
        if button
        else None,
    ]
    return tuple(row for row in found if row is not None)


def _form_decision(launch: CampaignLaunch, stored: dict[str, Any]) -> Decision | None:
    refs = launch.created_refs if isinstance(launch.created_refs, dict) else {}
    made = ref_field.ref_ids(refs, LaunchStep.FORM)
    picked = launch.lead_form_external_id
    proposed = _labels(draft_field.proposal(stored, DraftSection.FORM))
    written = _labels((launch.answers or {}).get(LEAD_FORM_QUESTIONS))
    if not (picked or made or proposed or written):
        return None
    if picked and picked not in made:
        by = draft_field.source(stored, draft_field.LEAD_FORM)
        value = READY_FORM.get(by, UNKNOWN_FORM)
    else:
        by = _new_form_by(stored, proposed=proposed, written=written)
        value = NEW_FORM.get(by, UNKNOWN_FORM)
    return Decision(key="form", label="Lid formasi", value=value, by=by)


def _new_form_by(
    stored: dict[str, Any], *, proposed: frozenset[str], written: frozenset[str]
) -> str:
    if written:
        return draft_field.BY_AI if written == proposed else draft_field.BY_OWNER
    return (
        draft_field.BY_AI
        if proposed
        else draft_field.source(stored, draft_field.LEAD_FORM)
    )


def _section_by(stored: dict[str, Any], name: str) -> str:
    part = stored.get(name)
    if not isinstance(part, dict):
        return ""
    proposed, picked = part.get("ai"), part.get("chosen")
    if picked is None:
        return draft_field.BY_AI if proposed is not None else ""
    return draft_field.BY_AI if picked == proposed else draft_field.BY_OWNER


def _interests_by(stored: dict[str, Any], *, picks: frozenset[str]) -> str:
    """A saved copy of the AI's own picks is still the AI's choice."""
    proposed = draft_field.proposal(stored, DraftSection.INTERESTS)
    if not isinstance(proposed, list):
        return draft_field.BY_OWNER
    offered = _labels(draft_field.ai_picks(proposed))
    return draft_field.BY_AI if picks == offered else draft_field.BY_OWNER


def _labels(rows: Any) -> frozenset[str]:
    if not isinstance(rows, list):
        return frozenset()
    return frozenset(
        str(row.get("label", "")).strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("label", "")).strip()
    )


# -- the adverts -----------------------------------------------------------------


def _ads(
    db: Session, launch: CampaignLaunch, stored: dict[str, Any]
) -> tuple[LaunchAd, ...]:
    rows = db.scalars(
        select(LaunchCreative)
        .options(joinedload(LaunchCreative.media_asset))
        .where(LaunchCreative.launch_id == launch.id)
        .order_by(
            LaunchCreative.group, LaunchCreative.position, LaunchCreative.created_at
        )
    )
    proposed = draft_field.proposal(stored, DraftSection.CREATIVE)
    written = (
        [proposed]
        if isinstance(proposed, dict)
        else [row for row in proposed or [] if isinstance(row, dict)]
    )
    return tuple(_ad(row, proposed=written) for row in rows)


def _ad(row: LaunchCreative, *, proposed: list[dict[str, Any]]) -> LaunchAd:
    asset = row.media_asset
    picture = asset.thumbnail_url if asset is not None else ""
    return LaunchAd(
        id=row.id,
        position=row.position,
        name=row.ad_name,
        headline=row.headline,
        text=row.primary_text,
        description=row.description,
        words_by=_words_by(row, proposed=proposed),
        picture=picture if picture.startswith(("https://", "http://")) else "",
        is_video=asset.is_video if asset is not None else False,
        video_url=video_address(asset),
        media_kind_label=_media_label(row, asset),
        post_url=post_address(asset),
    )


def _words_by(row: LaunchCreative, *, proposed: list[dict[str, Any]]) -> str:
    if not row.primary_text.strip():
        return ""
    words = (row.primary_text.strip(), row.headline.strip(), row.description.strip())
    same = any(
        words
        == (
            str(item.get("primary_text", "")).strip(),
            str(item.get("headline", "")).strip(),
            str(item.get("description", "")).strip(),
        )
        for item in proposed
    )
    return draft_field.BY_AI if same else draft_field.BY_OWNER


def _media_label(row: LaunchCreative, asset: MediaAsset | None) -> str:
    if asset is not None:
        return str(MEDIA_KIND_LABELS.get(asset.kind, asset.kind))
    return str(MEDIA_KIND_LABELS[MediaKind.UPLOAD]) if row.media_upload else ""


def _address(url: str) -> str:
    return url if url.startswith(("https://", "http://")) else ""


def video_address(asset: MediaAsset | None) -> str:
    """Where a video can be watched: the file on the ad account, or its post."""
    if asset is None or not asset.is_video:
        return ""
    return _address(asset.permalink_url)


def post_address(asset: MediaAsset | None) -> str:
    """Where the chosen Facebook or Instagram post opens."""
    if asset is None or asset.kind not in POST_KINDS:
        return ""
    return _address(asset.permalink_url)


POST_KINDS: Final[frozenset[str]] = frozenset(
    {MediaKind.POST, MediaKind.IG_IMAGE, MediaKind.IG_VIDEO}
)


# -- the audience in words -------------------------------------------------------


def _place_names(stored: dict[str, Any]) -> dict[str, str]:
    """A spec names a city by key alone; the draft kept the name beside it."""
    audience = draft_field.chosen(stored, DraftSection.AUDIENCE)
    rows = geo_field.known_places(audience) + geo_field.areas(audience)
    return {row["key"]: row["name"] for row in rows if row["key"] and row["name"]}


def _places(places: tuple[Place, ...], names: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        f"{_place(place.name, names)}, {place.radius} {place.unit or 'km'} atrofida"
        if place.radius
        else _place(place.name, names)
        for place in places
    )


def _place(name: str, names: Mapping[str, str]) -> str:
    if name.startswith(_PIN):
        return f"Xaritadagi nuqta ({name.removeprefix(_PIN)})"
    return names.get(name) or str(_COUNTRIES.get(name, name))


def _ages(words: AudienceWords) -> str:
    low, high = words.age_min, words.age_max
    if low and high:
        return f"{low}-{high} yosh"
    if low:
        return f"{low} yoshdan katta"
    if high:
        return f"{high} yoshgacha"
    return "Yosh chegarasiz"


def _genders(value: str) -> str:
    return {"male": "Erkaklar", "female": "Ayollar"}.get(value, "Hammaga")


def _placements(words: AudienceWords) -> tuple[str, ...]:
    """One line per platform; none at all is the provider choosing."""
    lines = []
    for platform, positions in words.placements:
        name = PLATFORM_LABELS.get(platform, platform)
        spots = ", ".join(POSITION_LABELS.get(item, item) for item in positions)
        lines.append(f"{name}: {spots}" if spots else name)
    return tuple(lines)


def _attribution(answers: Mapping[str, Any]) -> str:
    value = str(answers.get(ATTRIBUTION) or "")
    return str(ATTRIBUTION_LABELS.get(value, value))


def _frequency_cap(answers: Mapping[str, Any]) -> tuple[int, int] | None:
    value = answers.get(FREQUENCY_CAP)
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    times, days = value
    return (times, days) if isinstance(times, int) and isinstance(days, int) else None


__all__ = [
    "POST_KINDS",
    "AudienceLines",
    "Decision",
    "LaunchAd",
    "LaunchSettings",
    "audience_lines",
    "launch_settings",
    "post_address",
    "video_address",
]
