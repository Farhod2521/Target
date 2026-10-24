"""What the first step offers, row by row - the one table every layer reads."""

from dataclasses import dataclass
from typing import Final, Literal

from core.targeting.campaign_types import (
    CAMPAIGN_TYPES,
    CampaignType,
    ObjectiveGroup,
    default_type,
)

Outcome = Literal[
    "requests", "calls", "messages", "visits", "profile", "reach", "sales"
]

Destination = Literal[
    "instant_form", "website", "calls", "messaging", "instagram_profile", "none"
]

Requirement = Literal["pixel", "quality_signal", "instagram", "not_built"]


@dataclass(frozen=True, slots=True)
class OutcomeSpec:
    """One answer to the first question and the goals behind it, default first."""

    key: Outcome
    goals: tuple[str, ...]
    live: bool = True
    recommended: str = ""


OUTCOMES: Final[tuple[OutcomeSpec, ...]] = (
    OutcomeSpec("requests", ("leads", "site_leads")),
    OutcomeSpec("calls", ("calls",)),
    OutcomeSpec("messages", ("messages",)),
    OutcomeSpec("visits", ("traffic",)),
    OutcomeSpec("profile", ("profile_visits",)),
    OutcomeSpec("reach", ("views",), recommended="seen_widely"),
    OutcomeSpec("sales", ("sales",), live=False),
)


@dataclass(frozen=True, slots=True)
class AccountFacts:
    """What the account has, as far as the rows care."""

    has_pixel: bool
    quality_ready: bool = False
    has_instagram: bool = False


@dataclass(frozen=True, slots=True)
class Offer:
    """One row: a campaign kind, and where the first step draws it."""

    kind: CampaignType
    outcome: Outcome
    destination: Destination
    provider_destination_label: str
    choice: str
    needs: tuple[Requirement, ...] = ()
    meaning: str = ""
    phrases: tuple[str, ...] = ()
    buildable: bool = True
    listed: bool = True

    @property
    def key(self) -> str:
        return self.kind.key

    @property
    def goal(self) -> str:
        return self.kind.goal

    @property
    def provider(self) -> str:
        return self.kind.provider

    @property
    def objective_group(self) -> ObjectiveGroup:
        return self.kind.objective_group

    @property
    def is_choice(self) -> bool:
        """Whether the row is one of the plain options of the second question."""
        return self.choice == self.key


_KINDS: Final[dict[str, CampaignType]] = {row.key: row for row in CAMPAIGN_TYPES}


def _kind(key: str) -> CampaignType:
    return _KINDS[key]


QUALITY_LEADS: Final = CampaignType(
    "meta",
    "leads",
    "form_quality_leads",
    "OUTCOME_LEADS",
    "QUALITY_LEAD",
    "Leads",
    "Maximize number of qualified leads",
    "leads",
)

OFFERS: Final[tuple[Offer, ...]] = (
    Offer(
        _kind("form_leads"),
        "requests",
        "instant_form",
        "Instant forms",
        "form_leads",
        meaning=(
            "The person fills in a short form inside the ad and leaves a name "
            "and phone number. The default for any request with no website "
            "mentioned."
        ),
        phrases=(
            "raqamini qoldirsin",
            "ariza qoldirsin",
            "zayavka",
            "kursga yozilsin",
            "оставили номер",
            "заявки",
        ),
    ),
    Offer(
        QUALITY_LEADS,
        "requests",
        "instant_form",
        "Instant forms",
        "form_leads",
        needs=("quality_signal",),
        meaning=(
            "The same form, bought on requests the owner later marked as good "
            "rather than on every request."
        ),
        phrases=("sifatli ariza", "faqat jiddiy arizalar", "качественные заявки"),
        buildable=False,
        listed=False,
    ),
    Offer(
        _kind("site_requests"),
        "requests",
        "website",
        "Website",
        "site_requests",
        needs=("pixel",),
        meaning=(
            "The person goes to the owner's website and leaves a request in "
            "the form there, counted by the pixel."
        ),
        phrases=(
            "saytda ariza qoldirsin",
            "saytimizdagi formani to'ldirsin",
            "заявка на сайте",
        ),
    ),
    Offer(
        _kind("site_requests_views"),
        "requests",
        "website",
        "Website",
        "site_requests",
        needs=("pixel",),
        meaning=(
            "A request on the website, bought on the request page opening. "
            "Only when the owner says the pixel does not count requests."
        ),
        phrases=("piksel arizani sanamayapti",),
        listed=False,
    ),
    Offer(
        _kind("site_requests_clicks"),
        "requests",
        "website",
        "Website",
        "site_requests",
        needs=("pixel",),
        meaning="A request on the website, bought on clicks on the link.",
        phrases=("ariza sahifasiga ko'p o'tsin",),
        listed=False,
    ),
    Offer(
        _kind("site_requests_reach"),
        "requests",
        "website",
        "Website",
        "site_requests",
        needs=("pixel",),
        meaning=(
            "A request on the website, shown to as many different people as possible."
        ),
        phrases=("ariza sahifasini ko'p odam ko'rsin",),
        listed=False,
    ),
    Offer(
        _kind("calls_many"),
        "calls",
        "calls",
        "Calls",
        "calls_many",
        meaning=(
            "The person taps a button on the ad and phones the business. "
            "The default for any call, whatever is said about the caller."
        ),
        phrases=(
            "qo'ng'iroq qilsin",
            "jiddiy mijoz qo'ng'iroq qilsin",
            "telefon qilsin",
            "позвонили",
        ),
    ),
    Offer(
        _kind("calls_engaged"),
        "calls",
        "calls",
        "Calls",
        "",
        meaning=(
            "A phone call, bought under the Engagement objective. Only when "
            "the owner names that objective."
        ),
        phrases=("Engagement maqsadida qo'ng'iroq",),
    ),
    Offer(
        _kind("calls_ready"),
        "calls",
        "calls",
        "Calls",
        "",
        meaning=(
            "A phone call, bought under the Leads objective. Only when the "
            "owner names that objective."
        ),
        phrases=("Leads maqsadida qo'ng'iroq",),
    ),
    Offer(
        _kind("chat_conversations"),
        "messages",
        "messaging",
        "Messaging apps",
        "chat_conversations",
        meaning=(
            "The person taps the ad and writes to the business in Instagram "
            "Direct or Messenger. The default for a message."
        ),
        phrases=(
            "yozsin",
            "Direct'ga yozsin",
            "xabar yuborsin",
            "savol bersin",
            "написали в директ",
        ),
    ),
    Offer(
        _kind("chat_link_clicks"),
        "messages",
        "messaging",
        "Messaging apps",
        "chat_conversations",
        meaning=(
            "A chat opened, bought on taps rather than on conversations: "
            "cheaper, fewer people actually write."
        ),
        phrases=("chatni ko'p bosishsin",),
    ),
    Offer(
        _kind("site_page_views"),
        "visits",
        "website",
        "Website",
        "site_page_views",
        meaning=(
            "The person opens the owner's website; counted when the page "
            "loads. The default for a visit."
        ),
        phrases=(
            "saytga kirsin",
            "saytni ko'rsin",
            "saytga o'tsin",
            "перешли на сайт",
        ),
    ),
    Offer(
        _kind("site_link_clicks"),
        "visits",
        "website",
        "Website",
        "site_link_clicks",
        meaning=(
            "A visit bought on clicks on the link, counted even when the page "
            "does not open: many cheap clicks."
        ),
        phrases=("havolani ko'p bosishsin", "ko'p bosish, arzon", "клики"),
    ),
    Offer(
        _kind("site_daily_reach"),
        "visits",
        "website",
        "Website",
        "",
        meaning="The website link shown to as many different people a day.",
        phrases=("har kuni yangi odamlar saytni ko'rsin",),
    ),
    Offer(
        _kind("site_impressions"),
        "visits",
        "website",
        "Website",
        "",
        meaning="The website link shown as many times as possible.",
        phrases=("sayt reklamasi ko'p chiqsin",),
    ),
    Offer(
        _kind("profile_visits"),
        "profile",
        "instagram_profile",
        "Instagram profile",
        "profile_visits",
        needs=("instagram",),
        meaning=(
            "The person taps the ad and lands on the business's own Instagram "
            "profile, where they can follow it or look through its posts. Not "
            "the website: only when the words name the profile, the Instagram "
            "page, or followers."
        ),
        phrases=(
            "profilga o'tsin",
            "profilimga odam kelsin",
            "obunachi ko'paysin",
            "batafsil bosib profilga kirsin",
            "Instagram sahifamni ko'rishsin",
        ),
    ),
    Offer(
        _kind("seen_widely"),
        "reach",
        "none",
        "",
        "seen_widely",
        meaning=(
            "Shown to as many different people as possible; nothing is asked of "
            "them. The default for being seen."
        ),
        phrases=(
            "ko'proq odam bilsin",
            "ko'proq odam ko'rsin",
            "tanishsin",
            "охват",
        ),
    ),
    Offer(
        _kind("seen_often"),
        "reach",
        "none",
        "",
        "seen_often",
        meaning=(
            "Shown as many times as possible; one person may see it several times."
        ),
        phrases=("ko'p marta ko'rsin", "esida tursin, qayta-qayta", "показы"),
    ),
    Offer(
        _kind("seen_remembered"),
        "reach",
        "none",
        "",
        "seen_remembered",
        meaning="Shown so that people remember the brand.",
        phrases=("brendni eslab qolsin", "esda qolsin", "запомнили бренд"),
    ),
)

_OFFERS_BY_KEY: Final[dict[tuple[str, str], Offer]] = {
    (row.provider, row.key): row for row in OFFERS
}
_BY_OUTCOME: Final[dict[tuple[str, str], tuple[Offer, ...]]] = {}
for _row in OFFERS:
    _BY_OUTCOME[(_row.provider, _row.outcome)] = (
        *_BY_OUTCOME.get((_row.provider, _row.outcome), ()),
        _row,
    )
_OUTCOMES_BY_KEY: Final[dict[str, OutcomeSpec]] = {row.key: row for row in OUTCOMES}
_OUTCOME_BY_GOAL: Final[dict[str, OutcomeSpec]] = {
    goal: row for row in OUTCOMES for goal in row.goals
}


def outcome_spec(key: str) -> OutcomeSpec | None:
    return _OUTCOMES_BY_KEY.get(key)


def outcome_of(goal: str) -> OutcomeSpec | None:
    """The first question's answer a stored goal belongs to."""
    return _OUTCOME_BY_GOAL.get(goal)


def offer(*, provider: str, key: str) -> Offer | None:
    return _OFFERS_BY_KEY.get((provider, key))


def offers_for(*, provider: str, outcome: str) -> tuple[Offer, ...]:
    """Every row under one answer to the first question, in screen order."""
    return _BY_OUTCOME.get((provider, outcome), ())


def listed_for(*, provider: str, outcome: str, keep: str = "") -> tuple[Offer, ...]:
    """The rows offered under one answer, in screen order."""
    return tuple(
        row
        for row in offers_for(provider=provider, outcome=outcome)
        if row.listed or row.key == keep
    )


def choices_for(*, provider: str, outcome: str) -> tuple[Offer, ...]:
    """The plain options of the second question, in screen order."""
    return tuple(
        row for row in listed_for(provider=provider, outcome=outcome) if row.is_choice
    )


def default_offer(*, provider: str, goal: str) -> Offer | None:
    """What a goal is bought as when nobody chose - the table's default kind."""
    kind = default_type(provider=provider, goal=goal)
    return offer(provider=provider, key=kind.key) if kind is not None else None


def outcome_default(*, provider: str, outcome: str) -> Offer | None:
    """What an outcome is bought as when only the first question is answered."""
    spec = outcome_spec(outcome)
    if spec is None or not spec.live:
        return None
    if spec.recommended:
        found = offer(provider=provider, key=spec.recommended)
        if found is not None:
            return found
    return default_offer(provider=provider, goal=spec.goals[0])


def closed_by(row: Offer, facts: AccountFacts) -> tuple[Requirement, ...]:
    """What stops this row for this account. Empty when it is open."""
    missing: list[Requirement] = []
    if "pixel" in row.needs and not facts.has_pixel:
        missing.append("pixel")
    if "quality_signal" in row.needs and not facts.quality_ready:
        missing.append("quality_signal")
    if "instagram" in row.needs and not facts.has_instagram:
        missing.append("instagram")
    if not row.buildable and not missing:
        missing.append("not_built")
    return tuple(missing)


def is_open(row: Offer, facts: AccountFacts) -> bool:
    return not closed_by(row, facts)


def needs_pixel(*, provider: str, key: str) -> bool:
    """Whether the row can only be created with a pixel reporting results."""
    found = offer(provider=provider, key=key)
    return found is not None and "pixel" in found.needs


def nearest_open(
    row: Offer, facts: AccountFacts, *, preferred: tuple[str, ...] = ()
) -> Offer | None:
    """The best row to offer instead of a closed one, or ``None``."""
    same_outcome = listed_for(provider=row.provider, outcome=row.outcome)
    named = tuple(
        found
        for key in preferred
        if (found := offer(provider=row.provider, key=key)) is not None
        and found.outcome == row.outcome
        and found.listed
    )
    sibling = tuple(other for other in same_outcome if other.choice == row.choice)
    default = outcome_default(provider=row.provider, outcome=row.outcome)
    fallback: tuple[Offer, ...] = (default,) if default is not None else ()
    candidates: tuple[Offer, ...] = (*named, *sibling, *fallback, *same_outcome)
    for candidate in candidates:
        if candidate.key != row.key and is_open(candidate, facts):
            return candidate
    return None


__all__ = [
    "OFFERS",
    "OUTCOMES",
    "QUALITY_LEADS",
    "AccountFacts",
    "Destination",
    "Offer",
    "Outcome",
    "OutcomeSpec",
    "Requirement",
    "choices_for",
    "closed_by",
    "default_offer",
    "is_open",
    "listed_for",
    "nearest_open",
    "needs_pixel",
    "offer",
    "offers_for",
    "outcome_default",
    "outcome_of",
    "outcome_spec",
]
