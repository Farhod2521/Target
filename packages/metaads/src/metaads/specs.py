"""What goes out: the shapes a campaign is asked for in."""

from typing import Any, Final
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from metaads.dto import MetaDTO

STATUS_PAUSED: Final = "PAUSED"
STATUS_ACTIVE: Final = "ACTIVE"

CTA_SIGN_UP: Final = "SIGN_UP"

CTA_NO_BUTTON: Final = "NO_BUTTON"

MAX_QUESTION_CHARS: Final = 80
MAX_WELCOME_QUESTIONS: Final = 4


def checked_questions(questions: tuple[str, ...]) -> tuple[str, ...]:
    """Refuse a question Meta would refuse, before anything is created."""
    for question in questions:
        if not question.strip():
            raise ValueError("a welcome question cannot be blank")
        if len(question) > MAX_QUESTION_CHARS:
            raise ValueError(
                f"a welcome question is at most {MAX_QUESTION_CHARS} characters"
            )
    return questions


TEL_SCHEME: Final = "tel:"

APP_DESTINATIONS: Final[frozenset[str]] = frozenset(
    {"MESSENGER", "INSTAGRAM_DIRECT", "WHATSAPP"}
)

MAX_WELCOME_TEXT: Final = 300
MAX_AUTOFILL_TEXT: Final = 300

PROVIDER_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "facebook.com",
        "fb.com",
        "fb.me",
        "instagram.com",
        "instagr.am",
        "messenger.com",
    }
)

BID_LOWEST_COST: Final = "LOWEST_COST_WITHOUT_CAP"
BID_COST_CAP: Final = "COST_CAP"

CAPPED_STRATEGIES: Final[frozenset[str]] = frozenset({BID_COST_CAP})

QUESTION_CUSTOM: Final = "CUSTOM"
STANDARD_QUESTIONS: Final = frozenset(
    {
        "FULL_NAME",
        "FIRST_NAME",
        "LAST_NAME",
        "EMAIL",
        "PHONE",
        "CITY",
        "STATE",
        "COUNTRY",
        "ZIP",
        "STREET_ADDRESS",
    }
)


class CampaignSpec(MetaDTO):
    """The top object: a name, a goal, and what the law says about it."""

    name: str
    objective: str
    special_ad_categories: tuple[str, ...] = ()
    special_ad_category_country: tuple[str, ...] = ()
    status: str = STATUS_PAUSED
    budget_sharing: bool = False
    spend_cap_minor: int = 0


class AdSetSpec(MetaDTO):
    """The audience and the money. The layer that actually spends."""

    name: str
    campaign_id: str
    daily_budget_minor: int
    optimization_goal: str
    billing_event: str
    destination_type: str = ""
    targeting: dict[str, Any] = Field(default_factory=dict)
    promoted_object: dict[str, Any] = Field(default_factory=dict)
    start_time: str = ""
    end_time: str = ""
    status: str = STATUS_PAUSED
    bid_strategy: str = BID_LOWEST_COST
    bid_amount_minor: int = 0
    daily_min_spend_minor: int = 0
    daily_max_spend_minor: int = 0
    attribution: tuple[dict[str, Any], ...] = ()
    frequency_control: tuple[dict[str, Any], ...] = ()

    @model_validator(mode="after")
    def _a_capped_strategy_carries_its_cap(self) -> "AdSetSpec":
        """Refuse the pair Meta refuses, here rather than there."""
        capped = self.bid_strategy in CAPPED_STRATEGIES
        if capped and self.bid_amount_minor <= 0:
            raise ValueError(f"{self.bid_strategy} needs a bid amount above zero")
        if not capped and self.bid_amount_minor:
            raise ValueError(
                f"{self.bid_strategy} takes no bid amount; got {self.bid_amount_minor}"
            )
        return self


CAROUSEL_MIN_CARDS: Final = 2
CAROUSEL_MAX_CARDS: Final = 10


class CarouselCard(MetaDTO):
    """One picture or video in a carousel advert, as the ad account names it.

    The same asymmetry as :class:`CreativeSpec`: an image by its hash, a
    video by its id - and a video card still needs a still beside it, which
    Meta refuses the card without.
    """

    image_hash: str = ""
    video_id: str = ""
    thumbnail_url: str = ""


class CreativeSpec(MetaDTO):
    """The words and the picture, as one object.

    ``image_hash`` and ``video_id`` are the same asymmetry the read side
    documents: Meta names an image by its hash and everything else by an
    id. Exactly one of the two is set, and which one decides the entire
    shape of the story spec that gets built from this.
    """

    name: str
    page_id: str
    message: str
    link_url: str
    headline: str = ""
    description: str = ""
    image_hash: str = ""
    video_id: str = ""
    thumbnail_url: str = ""
    lead_form_id: str = ""
    call_to_action: str = CTA_SIGN_UP
    app_destination: str = ""
    phone_number: str = ""
    welcome_text: str = ""
    autofill_text: str = ""
    welcome_questions: tuple[str, ...] = Field(
        default=(), max_length=MAX_WELCOME_QUESTIONS
    )

    @field_validator("welcome_questions")
    @classmethod
    def _questions_fit(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return checked_questions(value)

    instagram_user_id: str = ""
    url_tags: str = ""
    cards: tuple[CarouselCard, ...] = ()

    @model_validator(mode="after")
    def _a_carousel_has_room(self) -> "CreativeSpec":
        """Meta's bounds, and one picture slot rather than two."""
        if not self.cards:
            return self
        if not CAROUSEL_MIN_CARDS <= len(self.cards) <= CAROUSEL_MAX_CARDS:
            raise ValueError(
                f"a carousel takes {CAROUSEL_MIN_CARDS}-{CAROUSEL_MAX_CARDS} "
                f"cards, not {len(self.cards)}"
            )
        if self.image_hash or self.video_id:
            raise ValueError("a carousel carries its pictures in its cards")
        return self

    @model_validator(mode="after")
    def _lead_ads_link_outside_meta(self) -> "CreativeSpec":
        """Refuse a lead creative pointed back at Meta, here rather than there."""
        if not self.lead_form_id:
            return self
        if not is_external(self.link_url):
            raise ValueError(
                f"a lead creative needs a link outside Meta, not {self.link_url!r}"
            )
        return self

    @model_validator(mode="after")
    def _a_dialable_number_is_dialable(self) -> "CreativeSpec":
        """Refuse a number that is not in the form Meta dials."""
        if not self.phone_number:
            return self
        digits = self.phone_number.removeprefix("+")
        if not self.phone_number.startswith("+") or not digits.isdigit():
            raise ValueError(f"not an E.164 phone number: {self.phone_number!r}")
        return self

    @model_validator(mode="after")
    def _messaging_destination_is_one_meta_knows(self) -> "CreativeSpec":
        """Refuse an app destination Meta does not have a surface for."""
        if self.app_destination and self.app_destination not in APP_DESTINATIONS:
            raise ValueError(
                f"not a messaging destination Meta knows: {self.app_destination!r}"
            )
        return self


class LeadQuestionSpec(MetaDTO):
    """One question on a lead form, in Meta's vocabulary.

    ``kind`` is Meta's question type. Turning the domain's own words into
    these belongs above this package; what is enforced below is that a
    custom question carries the key and options Meta needs and a standard
    one carries neither, because Meta rejects a standard question that
    arrives with a label attached.
    """

    kind: str
    label: str = ""
    options: tuple[str, ...] = ()

    @property
    def is_custom(self) -> bool:
        return self.kind.upper() not in STANDARD_QUESTIONS


THANK_YOU_NONE: Final = "NONE"
THANK_YOU_WEBSITE: Final = "VIEW_WEBSITE"
THANK_YOU_CALL: Final = "CALL_BUSINESS"
THANK_YOU_BUTTONS: Final[frozenset[str]] = frozenset(
    {
        THANK_YOU_NONE,
        THANK_YOU_WEBSITE,
        THANK_YOU_CALL,
        "MESSAGE_BUSINESS",
        "DOWNLOAD",
        "SCHEDULE_APPOINTMENT",
        "VIEW_ON_FACEBOOK",
        "PROMO_CODE",
        "WHATSAPP",
        "P2B_MESSENGER",
        "BOOK_ON_WEBSITE",
    }
)


class LeadFormSpec(MetaDTO):
    """The form itself: what is asked, and the promise attached to asking.

    ``privacy_policy_url`` has no default. Meta requires it on every lead
    form, and a form without one is refused after the campaign, ad set and
    creative already exist - so it is required at construction instead.
    """

    name: str
    privacy_policy_url: str
    questions: tuple[LeadQuestionSpec, ...] = ()
    thank_you_title: str = ""
    thank_you_body: str = ""
    thank_you_button: str = ""
    thank_you_button_text: str = ""
    thank_you_url: str = ""
    thank_you_phone: str = ""
    thank_you_country: str = ""
    locale: str = ""
    higher_intent: bool = False

    @property
    def thank_you_type(self) -> str:
        """The button Meta is asked for, with the empty field resolved."""
        if self.thank_you_button:
            return self.thank_you_button
        return THANK_YOU_WEBSITE if self.thank_you_url else THANK_YOU_NONE

    @model_validator(mode="after")
    def _thank_you_button_has_what_it_needs(self) -> "LeadFormSpec":
        """Refuse a button that Meta would refuse, before the form is sent."""
        button = self.thank_you_type
        if button not in THANK_YOU_BUTTONS:
            raise ValueError(f"not a thank-you button Meta knows: {button!r}")
        if button == THANK_YOU_NONE:
            return self
        if not self.thank_you_title:
            raise ValueError("a thank-you button needs a thank-you title")
        if button == THANK_YOU_WEBSITE and not is_external(self.thank_you_url):
            raise ValueError(f"not an address outside Meta: {self.thank_you_url!r}")
        if button == THANK_YOU_CALL and not _dialable(self.thank_you_phone):
            raise ValueError(f"not an E.164 phone number: {self.thank_you_phone!r}")
        return self


def _dialable(number: str) -> bool:
    """Whether a string can be a ``tel:`` URI - a plus and digits."""
    digits = number.removeprefix("+")
    return number.startswith("+") and digits.isdigit()


def is_external(url: str) -> bool:
    """Whether a link leaves Meta - the whole of what 1815316 asks."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return False
    return not any(
        host == blocked or host.endswith(f".{blocked}") for blocked in PROVIDER_HOSTS
    )


INSTAGRAM_HOSTS: Final[frozenset[str]] = frozenset({"instagram.com", "instagr.am"})


def is_instagram(url: str) -> bool:
    """Whether a link opens something on Instagram rather than a site."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(
        host == instagram or host.endswith(f".{instagram}")
        for instagram in INSTAGRAM_HOSTS
    )


def instagram_profile_url(username: str) -> str:
    """The address a profile visit advert's button opens."""
    handle = username.strip().removeprefix("@").strip("/")
    return f"https://www.instagram.com/{handle}"
