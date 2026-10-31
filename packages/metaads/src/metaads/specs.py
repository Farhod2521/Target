"""What goes out: the shapes a campaign is asked for in.

The mirror image of :mod:`metaads.dto`. Those models describe what Meta
sends back; these describe what we send, and they exist for the same
reason - a create call taking eleven positional-looking parameters is a
call somebody eventually passes in the wrong order, and the two that
matter here are a headline and a description that read fine either way.

Everything is in Meta's own vocabulary, because that is what is being
sent. Translating from the domain happens above this package.

The required fields are required on purpose. ``page_id`` on a creative and
``privacy_policy_url`` on a lead form have no sensible default: Meta
refuses both, several calls into a sequence that has already created a
campaign, and failing here instead costs nothing.
"""

from typing import Any, Final
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from metaads.dto import MetaDTO

# Nothing is created running. A campaign that starts delivering the moment
# it is written spends money in the gap between the last create call and
# its owner seeing the result - and that gap contains every way the rest of
# the sequence can fail.
STATUS_PAUSED: Final = "PAUSED"
STATUS_ACTIVE: Final = "ACTIVE"

# Meta's word for "this ad collects leads through a form Meta hosts".
CTA_SIGN_UP: Final = "SIGN_UP"

# Meta's word for "draw no button". A real enum value rather than an
# absence, and the two are not the same thing: an omitted call to action
# lets Meta pick one, and what it picks is a link.
#
# The ad that wants this is the one bought on impressions - seen, not acted
# on. Every other creative in this package has somewhere for the tap to
# land, so this is the only value that makes ``call_to_action`` disappear
# from the story spec rather than change what is inside it.
CTA_NO_BUTTON: Final = "NO_BUTTON"

# Meta's ceiling on one question's words: "Icebreaker titles must not be
# more than 80 characters." The count is not documented; four is the most
# Meta's own page-level questions take, and the most asked for here.
MAX_QUESTION_CHARS: Final = 80
MAX_WELCOME_QUESTIONS: Final = 4


def checked_questions(questions: tuple[str, ...]) -> tuple[str, ...]:
    """Refuse a question Meta would refuse, before anything is created.

    Shared by both creative shapes - a new post and a post promoted where
    it stands carry the same welcome screen.
    """
    for question in questions:
        if not question.strip():
            raise ValueError("a welcome question cannot be blank")
        if len(question) > MAX_QUESTION_CHARS:
            raise ValueError(
                f"a welcome question is at most {MAX_QUESTION_CHARS} characters"
            )
    return questions


# The scheme a dialable number is written with inside the button. Meta's
# spelling, from the call-ads guide: ``{"link": "tel:+<country><number>"}``
# in the very key an ordinary ad carries a web address in.
#
# Added here rather than by the caller, because the caller holds a phone
# number and this package holds the knowledge that Meta wants it as a URI.
# A caller passing ``tel:`` itself would be a caller that had to know.
TEL_SCHEME: Final = "tel:"

# Where a messaging ad's button hands the person over to, in Meta's own
# vocabulary. Not a link: the button on one of these carries
# ``{"app_destination": ...}`` where an ordinary ad carries
# ``{"link": ...}``, and an ad built the second way is not broken - it is a
# working website ad sold to somebody who was promised a conversation, and
# nothing in the reporting afterwards says so.
#
# The three Meta documents, and no more. An unknown value is refused at
# construction rather than sent: this object is the last one built before
# the ad, so a refusal here costs nothing and a refusal there costs a
# campaign, an ad set and an upload.
APP_DESTINATIONS: Final[frozenset[str]] = frozenset(
    {"MESSENGER", "INSTAGRAM_DIRECT", "WHATSAPP"}
)

# The provider's own ceilings on what is written in the thread before the
# customer arrives. Meta refuses the creative past them.
MAX_WELCOME_TEXT: Final = 300
MAX_AUTOFILL_TEXT: Final = 300

# Hosts a lead ad may not point at. Meta's rule, not ours: a lead creative
# has to link to content outside Meta (100/1815316, "Lead Ad Creative Does
# Not Use External URL") even though nobody ever follows the link - tapping
# the ad opens the form. A page's own address is the obvious filler and the
# one the refusal names, which is why it is listed first.
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

# The bid strategy that asks the owner for nothing, and the one that asks
# for the only number they can actually answer.
#
# Meta has four. Two of them - a bid cap and a minimum ROAS - are media
# buyer's questions: what to pay per auction, what return to demand on a
# sale nobody here is measuring. Neither has an answer somebody running a
# clinic could give, and a number invented on their behalf silently decides
# how much of their budget gets spent.
#
# ``COST_CAP`` is different in kind, which is why it is the one offered.
# It says "do not pay more than this per result" - which is the
# sentence every advertiser here already says out loud, in their own
# currency, about their own leads. It is also the only one of the four
# whose number this product could sanity-check, because it is denominated
# in the same units as the budget beside it.
#
# **Both of the capped strategies need the number.** Meta refuses the ad
# set outright when the strategy implies one and none was sent, which is
# what the validator below exists to catch before the call rather than
# after a campaign already exists.
BID_LOWEST_COST: Final = "LOWEST_COST_WITHOUT_CAP"
BID_COST_CAP: Final = "COST_CAP"
BID_CAP: Final = "LOWEST_COST_WITH_BID_CAP"

# The strategies that carry an amount. A set rather than one name, so that
# the day a second one is offered the rule below already covers it.
CAPPED_STRATEGIES: Final[frozenset[str]] = frozenset({BID_COST_CAP, BID_CAP})

# Meta's own question types. Everything not in here is asked as CUSTOM,
# which is the difference between a field Meta prefills from the person's
# profile and one they type out on a phone.
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
    # Housing, employment and credit. Set here and inherited by everything
    # underneath - it cannot be added to a campaign afterwards, which is why
    # it travels with the very first call of the sequence.
    special_ad_categories: tuple[str, ...] = ()
    # Where a campaign with a category runs, ISO-3166 alpha-2. Required
    # beside a category; left out, Meta takes the account's tax country,
    # which an account may never have set.
    special_ad_category_country: tuple[str, ...] = ()
    status: str = STATUS_PAUSED
    # Whether ad sets may lend each other a fifth of their budget. Meta
    # demands an explicit answer from any campaign that does not carry its
    # own budget, and refuses the create call outright without one.
    #
    # False unless the owner chose it: the daily number they typed for an
    # audience is a promise a redistribution nobody showed them would break.
    # It cannot be switched on once the campaign runs, so it is asked here.
    budget_sharing: bool = False
    # The daily budget when the campaign holds it, which is the whole of
    # how Meta's Advantage campaign budget is switched on: there is no flag.
    # Zero when the ad sets hold their own.
    daily_budget_minor: int = 0
    # Required beside a budget here, and beside sharing: both make the
    # strategy the campaign's rather than the ad set's.
    bid_strategy: str = ""
    # The most this campaign may spend in total, in the account currency's
    # smallest unit. Zero means no ceiling, which is what every campaign
    # has unless somebody set one.
    #
    # A ceiling and not a rate: the daily budget on the ad set says how
    # fast, this says how far. Meta stops delivery when it is reached and
    # has its own minimum per currency - refused as an ordinary Graph error
    # rather than checked here, because that figure is Meta's to change.
    spend_cap_minor: int = 0

    @model_validator(mode="after")
    def _a_budget_settles_who_holds_the_strategy(self) -> "CampaignSpec":
        """Refuse the pairs Meta refuses, before anything exists to roll back."""
        if self.daily_budget_minor and self.budget_sharing:
            raise ValueError("a campaign budget leaves ad sets nothing to share")
        if (self.daily_budget_minor or self.budget_sharing) and not self.bid_strategy:
            raise ValueError("a campaign budget or sharing needs a bid strategy")
        return self


class AdSetSpec(MetaDTO):
    """The audience and the money. The layer that actually spends."""

    name: str
    campaign_id: str
    # Zero when the campaign above holds the budget. The strategy is then the
    # campaign's too, so ``bid_strategy`` below stays home; a cap does not.
    daily_budget_minor: int = 0
    optimization_goal: str
    billing_event: str
    destination_type: str = ""
    targeting: dict[str, Any] = Field(default_factory=dict)
    # What the ad set optimises towards when that is an event somewhere
    # else - a purchase on the advertiser's own site. Empty for a lead form
    # Meta hosts itself, which is most of what this product creates.
    promoted_object: dict[str, Any] = Field(default_factory=dict)
    # ISO-8601 with an offset, or empty for "start now". A string rather than
    # a datetime because this package has no clock and no timezone: the
    # caller knows the business's, and this must not guess it.
    start_time: str = ""
    # When it stops, in the same shape and for the same reason. Empty means
    # it runs until somebody stops it, which is what every ad set this
    # product has created does.
    #
    # **Allowed beside a daily budget**, unlike the hour-by-hour schedule
    # Meta only accepts with a lifetime one. An end in the past is refused
    # by Meta rather than here: what "past" means depends on a clock this
    # package does not have.
    end_time: str = ""
    status: str = STATUS_PAUSED
    # Sent explicitly rather than left to Meta. There is a default, and it
    # is not reliably this one: an ad set that inherits a capped strategy
    # with no cap to go with it is refused, and the refusal names the bid
    # field rather than the inheritance that produced it.
    bid_strategy: str = BID_LOWEST_COST
    # The most this ad set may pay for one result, in the account
    # currency's smallest unit. Zero on every ad set that names no cap,
    # which is what ``LOWEST_COST_WITHOUT_CAP`` means.
    #
    # An integer like every other amount in this package. Meta reads this
    # field in minor units - unlike the ``value`` on a conversion event
    # next door, which it reads in whole currency - and the two being
    # different is the reason neither is converted anywhere but at the one
    # boundary that knows which it is looking at.
    bid_amount_minor: int = 0
    # The least and the most this ad set may spend on one day, in the
    # account currency's smallest unit. Zero means neither is set, which is
    # what an ad set left to pace itself carries.
    #
    # The pair is how an advertiser says "never less than this, never more
    # than that" around a daily budget the provider is otherwise free to
    # spend unevenly across the day. Meta has its own floor for both and
    # refuses the ad set when they cross; neither is checked here, for the
    # reason the campaign's ceiling is not.
    daily_min_spend_minor: int = 0
    daily_max_spend_minor: int = 0
    # How long after seeing or tapping the advert a result still counts as
    # this advert's. Meta's own shape, a list of one or two entries:
    # ``[{"event_type": "CLICK_THROUGH", "window_days": 7}, ...]``.
    #
    # Empty means the provider's own default for this optimisation goal,
    # which is what every ad set carries unless somebody chose otherwise.
    # **Which windows a goal accepts is not documented** - Meta refuses the
    # pairing at creation, naming the field - so nothing here is checked
    # and a refusal is a refusal like any other.
    attribution: tuple[dict[str, Any], ...] = ()
    # The most times one person may be shown this advert, and over how many
    # days: ``[{"event": "IMPRESSIONS", "interval_days": 7, "max_frequency": 2}]``.
    #
    # Meta accepts it on the awareness objective and refuses it elsewhere,
    # which is the caller's business rather than this package's. Empty is
    # the ordinary state and lets the provider decide.
    frequency_control: tuple[dict[str, Any], ...] = ()

    @model_validator(mode="after")
    def _a_capped_strategy_carries_its_cap(self) -> "AdSetSpec":
        """Refuse the pair Meta refuses, here rather than there.

        Both halves, because both are silent failures of different kinds. A
        capped strategy with no amount is rejected by Meta after the
        campaign already exists - one call into the sequence, with a
        rollback to run. An amount sent beside the uncapped strategy is
        worse: Meta accepts it and ignores it, so the ad set delivers with
        no cap at all while every screen in this product says it has one.
        """
        capped = self.bid_strategy in CAPPED_STRATEGIES
        if capped and self.bid_amount_minor <= 0:
            raise ValueError(f"{self.bid_strategy} needs a bid amount above zero")
        if not capped and self.bid_amount_minor:
            raise ValueError(
                f"{self.bid_strategy} takes no bid amount; got {self.bid_amount_minor}"
            )
        return self


# How many cards a carousel creative takes. Meta's own bounds for
# ``child_attachments``: "A 2-10 element array of link objects".
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
    # Required, and required outside Meta. Meta wants a link on every
    # creative and will not follow this one - the tap opens the form - but
    # it refuses a lead creative whose link points back at a page. There is
    # no default because there is no honest one: the destination is the
    # advertiser's, and guessing it is what produces the refusal.
    link_url: str
    headline: str = ""
    description: str = ""
    image_hash: str = ""
    video_id: str = ""
    # Required by Meta for a video creative and ignored for an image one.
    thumbnail_url: str = ""
    lead_form_id: str = ""
    call_to_action: str = CTA_SIGN_UP
    # Which messaging surface the button opens, for the ads that open one.
    # Empty on everything else, which is most ads: an ordinary creative's
    # button carries a link and this decides that it does not.
    app_destination: str = ""
    # The number the button dials, on a call ad. E.164 - a plus and digits,
    # no scheme: ``tel:`` is Meta's spelling of it and is added where the
    # story spec is built.
    #
    # Empty on every other ad, and empty on a call ad is the failure this
    # field exists to make impossible to reach silently. Meta reads the
    # number out of ``call_to_action.value.link``, which is the same key an
    # ordinary ad puts a web address in - so a call creative built without
    # one is not refused. It is a working website ad with "Call now"
    # written on the button.
    phone_number: str = ""
    # What is already in the thread when somebody arrives from a messaging
    # ad: the business greeting them, and the line their own message box
    # opens pre-typed with. Both empty is normal and is not a blank
    # conversation - Meta writes its own greeting when none is sent.
    #
    # Two plain strings rather than the nested object Meta wants, because
    # the shape of that object is this package's job and knowing it is
    # exactly what a caller should not have to. See
    # ``metaads.stories.welcome_message``.
    welcome_text: str = ""
    autofill_text: str = ""
    # Questions the customer taps instead of typing. Empty is the normal
    # case and keeps the pre-typed line above; any at all replace it, because
    # Meta's welcome screen holds one or the other.
    welcome_questions: tuple[str, ...] = Field(
        default=(), max_length=MAX_WELCOME_QUESTIONS
    )

    @field_validator("welcome_questions")
    @classmethod
    def _questions_fit(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return checked_questions(value)

    # Runs the ad under the business's Instagram account as well. Empty is
    # the normal case - most advertisers here have a page and nothing else.
    #
    # **The provider renamed this.** It was ``instagram_actor_id`` until
    # v22.0; Meta retired that spelling for every API version on
    # 2025-09-09 and the v26.0 object story spec does not list it at all.
    # The value is unchanged - a page's Instagram business account id - and
    # only the word Meta reads it under is different, which is exactly the
    # kind of rename that fails silently: a nested spec carrying an unknown
    # key is not refused, it is ignored, and the ad runs without the
    # account it was supposed to run as.
    instagram_user_id: str = ""
    # What gets appended to the address when somebody taps the ad, so the
    # advertiser's own analytics can say where a visitor came from.
    #
    # A query string in the advertiser's vocabulary - ``utm_source`` and the
    # rest are a convention of the tool reading them, not of Meta - carrying
    # placeholders that are Meta's: it substitutes ``{{campaign.name}}`` and
    # its siblings when the ad is served. Sent as written, because the one
    # thing this package must not do with it is guess: a tag string it
    # "corrected" would quietly re-attribute every visit.
    #
    # Empty is the ordinary state and means the address is used as it is.
    url_tags: str = ""
    # Several pictures in one advert, in the order they are swiped. Empty
    # is every ordinary advert; set, it replaces ``image_hash`` and
    # ``video_id``, which stay empty. An Instagram carousel that cannot be
    # promoted where it stands is rebuilt this way rather than cut into
    # one advert per slide.
    cards: tuple[CarouselCard, ...] = ()

    @model_validator(mode="after")
    def _a_carousel_has_room(self) -> "CreativeSpec":
        """Meta's bounds, and one picture slot rather than two.

        Checked here for the reason every rule in this class is: this is
        the last object before the ad, and a carousel of one card or of
        eleven is refused only after the campaign and the ad set exist.
        """
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
        """Refuse a lead creative pointed back at Meta, here rather than there.

        This is the last object before the ad, which makes it the most
        expensive place in the sequence to be refused: a campaign, an ad
        set and a form already exist, and the form is the one thing the
        rollback cannot remove. Checking at construction costs nothing and
        happens before the first call.

        **Lead creatives only, and it stays that way.** A creative that
        sends people to a website must also leave Meta, but that is not a
        rule this package can enforce: a creative promoting an event, a
        post or a page conversation points *inside* Meta on purpose, and
        widening this would refuse ads three other projects legitimately
        build. Which kind of ad this is, is known one layer up - see
        ``apps.ads.services.create_campaign``, where the launch gate asks
        it of a spec that knows its own destination.
        """
        if not self.lead_form_id:
            return self
        if not is_external(self.link_url):
            raise ValueError(
                f"a lead creative needs a link outside Meta, not {self.link_url!r}"
            )
        return self

    @model_validator(mode="after")
    def _a_dialable_number_is_dialable(self) -> "CreativeSpec":
        """Refuse a number that is not in the form Meta dials.

        E.164 and nothing else: a leading plus and at least a few digits.
        Checked here for the reason the two rules beside it are - this is
        the last object built before the ad, and a number Meta cannot dial
        produces no error at all. The button appears, the ad delivers, and
        the phone does not ring.

        Deliberately shallow. Whether the number belongs to a real operator
        in a real country is libphonenumber's question and is asked above
        this package, where the business's own country is known; what is
        asked here is only whether the string can be a ``tel:`` URI.
        """
        if not self.phone_number:
            return self
        digits = self.phone_number.removeprefix("+")
        if not self.phone_number.startswith("+") or not digits.isdigit():
            raise ValueError(f"not an E.164 phone number: {self.phone_number!r}")
        return self

    @model_validator(mode="after")
    def _messaging_destination_is_one_meta_knows(self) -> "CreativeSpec":
        """Refuse an app destination Meta does not have a surface for.

        Meta's own enum, checked rather than trusted, and for the same
        reason the rule above is checked here: this is the last object
        before the ad. A misspelled surface is accepted by nothing and
        discovered five calls in, with a campaign and an ad set already
        created.
        """
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
    # The key a custom question's answers come back under. Empty means the
    # positional one; a caller sets it when it must find the answer again
    # by name, whatever position the question ended up in.
    key: str = ""

    @property
    def is_custom(self) -> bool:
        return self.kind.upper() not in STANDARD_QUESTIONS


# The thank-you screen's button, in Meta's own vocabulary. Every value the
# reference lists, so a caller may ask for any of them; the three named are
# the ones whose extra field this package knows to send and to check.
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
    # What the thank-you screen's button does, as Meta's ``button_type``.
    # Empty reads the address below: a link out when there is one, no
    # button when there is not.
    thank_you_button: str = ""
    # The words on that button. Empty lets Meta print its own for the type.
    thank_you_button_text: str = ""
    # Where a link-out button goes.
    thank_you_url: str = ""
    # What a call button dials: E.164, and the ISO country it belongs to.
    thank_you_phone: str = ""
    thank_you_country: str = ""
    # Meta's locale code for the form's own chrome - its buttons and its
    # consent text. Empty lets Meta choose by the viewer, which is better
    # than sending a locale it does not support.
    locale: str = ""
    # Whether the form asks the person to confirm before sending. Meta's
    # "higher intent" form: one more screen, fewer submissions, and the
    # ones that arrive are from people who meant it.
    #
    # False is the default and the safe one. A campaign on a small daily
    # budget optimising towards a rarer event can fail to leave the
    # provider's learning phase at all, which is a worse outcome than
    # leads somebody has to sift.
    higher_intent: bool = False

    @property
    def thank_you_type(self) -> str:
        """The button Meta is asked for, with the empty field resolved."""
        if self.thank_you_button:
            return self.thank_you_button
        return THANK_YOU_WEBSITE if self.thank_you_url else THANK_YOU_NONE

    @model_validator(mode="after")
    def _thank_you_button_has_what_it_needs(self) -> "LeadFormSpec":
        """Refuse a button that Meta would refuse, before the form is sent.

        The form is the last object of a launch and the only one Meta will
        not delete, so a refusal met there leaves a campaign, an ad set and
        an ad behind. Each check here is the field that button cannot work
        without: a screen to put it on, an address for a link, and a
        number for a call.
        """
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
    """Whether a string can be a ``tel:`` URI - a plus and digits.

    Shallow on purpose, like the creative's check: whether the number is a
    real operator's is asked above this package, where the country is known.
    """
    digits = number.removeprefix("+")
    return number.startswith("+") and digits.isdigit()


def is_external(url: str) -> bool:
    """Whether a link leaves Meta - the whole of what 1815316 asks.

    A function rather than an inline check because the layer that chooses
    the destination needs the same answer, and two spellings of "is this a
    facebook url" drift apart in exactly the way that produces a refusal
    five calls into a sequence.
    """
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return False
    return not any(
        host == blocked or host.endswith(f".{blocked}") for blocked in PROVIDER_HOSTS
    )


# Instagram's own hosts, among the provider's. A link to one is a profile
# or a post somebody pasted where their site was asked for.
INSTAGRAM_HOSTS: Final[frozenset[str]] = frozenset({"instagram.com", "instagr.am"})


def is_instagram(url: str) -> bool:
    """Whether a link opens something on Instagram rather than a site."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(
        host == instagram or host.endswith(f".{instagram}")
        for instagram in INSTAGRAM_HOSTS
    )


def instagram_profile_url(username: str) -> str:
    """The address a profile visit advert's button opens.

    The profile visit ads guide puts exactly this in ``call_to_action``'s
    ``link`` and in the story's own - and a button without it is refused
    (``100/2061015``, probe 2026-09-28). Built from the handle rather than
    typed, so it is always the account the advert runs as.
    """
    handle = username.strip().removeprefix("@").strip("/")
    return f"https://www.instagram.com/{handle}"
