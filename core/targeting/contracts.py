"""What the owner told us, before and after it becomes a targeting spec.

Deliberately in the owner's vocabulary on the way in. "objective",
"lookalike" and "CBO" appear nowhere: the person filling this in runs a
business, not a media buying desk, and the translation into platform terms
is this package's job.

On the way out the vocabulary is the provider's, because the spec is what
gets sent. That asymmetry is intentional and documented in CLAUDE.md - an
``AudienceIntent`` abstraction invented from a single provider would be
shaped exactly like that provider.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from adskit import MinorUnits, TraitKind

from core.targeting.adjustments import Adjustment
from core.targeting.audiences import AudienceChoice
from core.targeting.destinations import (
    DEFAULT_CHAT_CHANNEL,
    AdDestination,
    ChatChannel,
    needs_lead_form,
    needs_link,
    needs_phone,
    opens_chat,
    opens_profile,
    shows_a_button,
)
from core.targeting.modes import DEFAULT_TARGETING_MODE, TargetingMode
from core.targeting.placements import DEFAULT_PLACEMENT_MODE, PlacementMode


@dataclass(frozen=True, slots=True)
class Interest:
    """One targetable interest, in both vocabularies at once.

    ``label`` is what the owner reads, ``query`` is what the provider is
    searched for, and they differ on purpose: the catalogue is searched in
    English, so "sartaroshxona" finds nothing where "Barbershop" finds the
    right entry.

    English is a decision, not an observation. A provider localises its
    catalogue to the ad account - the same interest is "Education" on one
    and "Образование" on another, with one id - so the adapter pins the
    language it asks in. Without that, half a list comes back unmatched
    depending on whose account it was.

    ``external_id`` stays empty until the provider confirmed the query. The
    name is the source of truth and the id is a cache, never the other way
    round: providers merge interests and retire ids without notice, and an
    id written into the catalogue fails at the worst possible moment -
    while the campaign is being created.

    ``kind`` says which of the provider's detailed-targeting catalogues the
    row comes from, and it is load-bearing twice over. It decides **which
    key of the spec** the row goes into - a life event written into the
    interests block is not refused, it is accepted and matched against
    nobody - and it decides **how the row is found**: an interest is
    searched for and confirmed fuzzily, while a behaviour and a life event
    are matched exactly against a list the platform publishes.

    Defaulted to ``interest``, so a row that names no kind is read as one.
    """

    label: str
    query: str
    kind: TraitKind = "interest"
    external_id: str = ""
    audience_size: int = 0

    @property
    def is_confirmed(self) -> bool:
        """Whether the provider agreed this interest exists."""
        return bool(self.external_id)


@dataclass(frozen=True, slots=True)
class ConversionSource:
    """Where a sale on the advertiser's own site is reported from.

    Meta calls it a pixel and Google calls it a conversion action; both are
    the same bargain - a tag on somebody else's website, sending events
    back, in exchange for being able to optimise towards a purchase rather
    than towards a click.

    Only goals that optimise for an off-site event need one. A campaign
    collecting leads through the provider's own form does not, which is why
    this is optional everywhere it appears: half the businesses this product
    is for have no website at all.
    """

    external_id: str
    name: str = ""

    @property
    def is_usable(self) -> bool:
        return bool(self.external_id)


@dataclass(frozen=True, slots=True)
class QualityLeads:
    """Whether this campaign buys qualified leads instead of submissions.

    The counterpart of :class:`ConversionSource` above, and the same bargain
    made about a different event. That one is a tag on the advertiser's own
    website reporting a sale; this is *this product* reporting a verdict -
    somebody answered the telephone and said the lead was real - back to the
    provider, so the provider can go and find more of that person.

    Three fields because three separate things have to be true, and each of
    them fails differently:

    * ``dataset_id`` empty means the verdicts are going nowhere. The goal
      would name an event the provider has never received.
    * ``qualified_recently`` too low means there is nothing to learn from.
      An optimiser asked for a rare event it cannot find delivers less, not
      worse - which looks like a broken campaign rather than a bad setting.
    * ``chosen`` false means the owner did not ask. Nothing here may switch
      a campaign onto a different optimisation goal on its own; see
      :func:`core.targeting.quality.goal_for`.

    Optional everywhere, like the conversion source: most launches are made
    by accounts that have never marked a lead, and those campaigns are built
    exactly as the preset describes.
    """

    dataset_id: str = ""
    qualified_recently: int = 0
    chosen: bool = False

    @property
    def is_reporting(self) -> bool:
        """Whether verdicts have somewhere to be sent at all."""
        return bool(self.dataset_id)


@dataclass(frozen=True, slots=True)
class BusinessProfile:
    """The advertiser, reduced to what targeting actually needs.

    Named ``Profile`` rather than ``DTO`` to keep it distinct from the
    ``Business`` table: this is a value assembled for one decision, not a
    mirror of a row.

    Everything here is something the advertiser said about themselves.
    Nothing here comes from the platform, which is why the currency is not
    on it.
    """

    name: str
    # A key in the preset catalog, not free text. Category plus goal is what
    # selects a preset, so an unknown value has to fail loudly.
    category: str
    # No currency here, deliberately. Money on an ad set is denominated by
    # the ad account it is billed from and by nothing else - the provider
    # would ignore a second opinion - so the one currency this package
    # needs arrives beside the budget it belongs to, as an argument to
    # ``build``. A field here would be a profile answering a question that
    # is not the profile's to answer.
    #
    # Strings rather than Decimal. These end up in a JSON column and in a
    # request body, and Decimal survives neither without a custom encoder;
    # converting once, where the row is read, beats converting at every
    # boundary and forgetting at one of them.
    lat: str = ""
    lng: str = ""
    city: str = ""
    # ISO-3166 alpha-2. Categories that deliver past the end of any radius -
    # an online shop, a tour operator - target this instead of a pin.
    country_code: str = ""
    # Provider locale ids. A list whose meaning belongs to the provider, so
    # it is carried rather than interpreted.
    locales: tuple[int, ...] = ()
    # housing / employment / credit, or empty - ours, not the provider's
    # spelling, which the builder applies. Legal, not a preference: it
    # decides which fields are allowed to exist at all.
    special_ad_category: str = ""
    timezone: str = ""
    phone: str = ""


@dataclass(frozen=True, slots=True)
class OnboardingAnswers:
    """The answers a preset is chosen and adapted from.

    Assembled from two columns rather than one. ``CampaignLaunch.answers``
    holds what the wizard asked; ``CampaignLaunch.draft`` holds what Claude
    proposed and the owner confirmed. A preset does not care which screen a
    number arrived on.

    The optional fields are ``None`` when nobody answered them, which is
    exactly what lets a preset's ``defaults`` block fill them in. Zero would
    not work: zero is a legal radius answer in a way that None is not.
    """

    category: str
    goal: str
    daily_budget_minor: MinorUnits
    # The most this campaign may pay for one result, in the same currency
    # and the same minor units as the budget above it.
    #
    # ``None`` when nobody answered: the provider spends the daily budget
    # and buys whatever the auction gives it. Not zero, for the reason the
    # radius is not zero - a cap of nothing is a legal number that means
    # something quite different from an unanswered question.
    #
    # Only some goals can carry one. See
    # :data:`core.targeting.budget.CAPPABLE_GOALS`: an ad bought to be seen
    # has no result to put a price on, and a figure attached to one would
    # be refused by the provider or, worse, ignored.
    max_result_cost_minor: MinorUnits | None = None
    # The most this campaign may spend in total. ``None`` when nobody set
    # one, which is nearly all of them.
    total_cap_minor: MinorUnits | None = None
    # Cities or regions as the owner named them. Resolving these to provider
    # location ids happens against the provider's own search endpoint -
    # hardcoded geo ids go stale without warning.
    geo: tuple[str, ...] = ()
    radius_km: int | None = None
    age_min: int | None = None
    age_max: int | None = None
    # Provider gender codes; empty means everyone. Codes rather than domain
    # words for the same reason the spec below is provider-shaped: one
    # mapping, at the form, instead of an abstraction invented too early.
    genders: tuple[int, ...] = ()
    # Already resolved against the provider where a connection existed.
    # Unconfirmed ones are kept rather than dropped - the screen has to be
    # able to say which name it could not find.
    interests: tuple[Interest, ...] = ()
    # How much of the audience decision is being kept. An **answer**, never
    # inferred from the spec, and that is the whole of what separates a
    # broad audience somebody chose from one that happened because every
    # interest failed confirmation - see
    # :func:`~core.targeting.validators.validate_launchable`.
    targeting_mode: TargetingMode = DEFAULT_TARGETING_MODE
    # Where the ad may appear. The second half of the same question the
    # mode above asks - that one is who sees it, this one is where - and an
    # answer for the same reason: the two states produce specs that differ
    # by absence, and absence is exactly what cannot be read back.
    #
    # A launch that answered no placement question arrives here as
    # ``standard``, which is what those campaigns are.
    placement_mode: PlacementMode = DEFAULT_PLACEMENT_MODE
    # Which messaging surface a chat goal opens on. Meaningless on every
    # other goal and carried anyway, like the radius a country-wide
    # campaign never uses: the answers are what the wizard collected, not
    # a set assembled per goal.
    #
    # Defaults to the one every advertiser has. A launch that answered no
    # channel question, and one whose owner was never offered the choice
    # because their page has no Instagram account, arrive here
    # identically - and both mean Messenger.
    chat_channel: ChatChannel = DEFAULT_CHAT_CHANNEL
    # Which kind of campaign buys the goal - a key from
    # :data:`core.targeting.campaign_types.CAMPAIGN_TYPES`. Empty when
    # nobody chose, and a key that belongs to another goal reads the same
    # way: both are built as the goal's default.
    campaign_type: str = ""
    # Which event on the advertiser's own site counts as the result - a key
    # from :data:`core.targeting.conversion_events.CONVERSION_EVENTS`.
    #
    # Empty on every goal the provider measures itself, and empty is also
    # what a website goal arrives with until somebody says otherwise: the
    # preset carries the event then, and this only ever replaces it. An
    # event no provider has a word for is ignored the same way, because the
    # alternative is an ad set bought against a name nothing sends.
    conversion_event: str = ""
    # What to append to the advertiser's own address, so their analytics
    # can say which advert brought a visitor. Empty means the address is
    # used as it is - see :mod:`core.targeting.tracking`.
    url_tags: str = ""
    # The word on the button, when the owner wants a different one from the
    # catalogue's. Empty - the ordinary case - keeps the preset's own, and
    # so does a word this kind of advert may not carry.
    call_to_action: str = ""
    # Which window decides whether a result belongs to this advert - a key
    # from :data:`core.targeting.attribution.WINDOWS`. Empty means the
    # provider's own, which is what every campaign carries unless somebody
    # deliberately narrowed it.
    attribution_key: str = ""
    # The most times one person may be shown the advert, and over how many
    # days. ``None`` lets the provider decide, and it is dropped for every
    # goal but the one bought to be seen.
    frequency_cap: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class BuiltTargeting:
    """A preset, filled in and checked. The only thing the saga sends.

    ``preset_key`` and ``preset_version`` travel with it because presets
    change and running ad sets do not: months later, the only way to explain
    why an ad set targets what it targets is to know which version built it.
    """

    objective: str
    optimization_goal: str
    billing_event: str
    destination_type: str
    targeting: Mapping[str, Any]
    daily_budget_minor: MinorUnits
    # Where the tap lands, and the button that does it - both straight off
    # the preset. Carried rather than looked up again because the launch
    # sequence has no catalogue and should not grow one: it is handed a
    # built spec and everything it needs has to be on it.
    sends_to: AdDestination
    call_to_action: str
    # The ad account's currency, carried beside the budget it denominates.
    # Not the advertiser's reporting preference and not convertible: the
    # provider bills the account in this and would ignore anything else,
    # so a spec saying otherwise would be a spec describing a campaign
    # that cannot exist.
    currency: str
    special_ad_categories: tuple[str, ...]
    preset_key: str
    preset_version: str
    # The most this ad set may pay for one result, once the goal has had a
    # say. ``None`` means uncapped.
    #
    # **The answer, filtered - not the answer.** A figure attached to a goal
    # that has no result to price is dropped here and reported as an
    # adjustment, so what reaches the provider is a cap that can exist. How
    # to *express* one is not in this package: "bid strategy" is a provider
    # concept with a provider's vocabulary, and translating an amount into
    # it is the job of the one module allowed to be shaped like a platform.
    # See ``apps.ads.services.meta_specs``.
    max_result_cost_minor: MinorUnits | None = None
    # The most this campaign may spend in total. ``None`` when nobody set
    # one, which is nearly all of them.
    total_cap_minor: MinorUnits | None = None
    # How many days after a tap and after a view a result still counts as
    # this advert's. ``None`` sends nothing and leaves the provider's own
    # default in place - which is what nearly every campaign here does.
    attribution_days: tuple[int, int] | None = None
    # The most times one person may be shown this advert, and over how many
    # days. ``None`` everywhere except a campaign bought to be seen.
    frequency_cap: tuple[int, int] | None = None
    # Which of the three this was built as, carried rather than derived.
    #
    # Deriving it would mean reading the spec back - "no detailed targeting
    # block, therefore broad" - and that is exactly the reading this field
    # exists to prevent. An audience with no interests because the
    # advertiser chose none and one with no interests because none survived
    # confirmation produce the identical spec, and only one of them may
    # launch.
    targeting_mode: TargetingMode = DEFAULT_TARGETING_MODE
    # Where the ad may appear, carried for the same reason as the mode
    # above and with a sharper edge: in the automatic state the spec holds
    # **no** placement key at all, so a screen or a rule reading the spec
    # back could not tell "the provider chooses" from "nobody asked". The
    # answer is the only place that distinction survives.
    placement_mode: PlacementMode = DEFAULT_PLACEMENT_MODE
    # What the ad set optimises towards when that is an event somewhere
    # else - a purchase on the advertiser's own site. Empty for every goal
    # the provider can measure on its own, which is most of them.
    promoted_object: Mapping[str, Any] = field(default_factory=dict)
    # Whether the preset asked for one. Kept apart from whether there is
    # one, because those are different failures: a goal that needs no
    # conversion source and a goal whose source is missing both arrive here
    # with an empty ``promoted_object``, and only the second may not launch.
    needs_conversion_source: bool = False
    # Whether ``optimization_goal`` above was upgraded to the quality goal.
    #
    # Carried rather than derived, for the reason ``targeting_mode`` is: a
    # screen or a gate reading the goal back would have to hold the set of
    # provider words that mean "quality", and that set is exactly what this
    # package spent ``core.metrics.outcomes`` learning not to copy around.
    # It is also the one field here whose value depends on a *count* taken
    # at build time, so re-deriving it later could answer differently about
    # a campaign that already exists.
    buys_qualified_leads: bool = False
    # Which of the advertiser's own audiences this is aimed at, carried
    # rather than derived - for the same reason ``targeting_mode`` above is.
    #
    # The spec holds ids and nothing else, and two of the questions asked
    # after the spec is built cannot be answered from an id: whether an
    # included audience is a lookalike, which a Special Ad Category may not
    # have, and what to call one on a screen. Reading them back out of a
    # list of numbers would mean a database round trip inside a gate that
    # has none of the rest of its answers there either.
    audiences: AudienceChoice = field(default_factory=AudienceChoice)
    # Where the ad points, when that is the thing being bought.
    #
    # Empty is normal and means two different things, which is why it is
    # never filled in here: on a goal that does not send anybody to a site
    # it means "not asked", and on one that does it means "not answered".
    # ``validate_launchable`` is what separates them, because only the
    # second may not launch. Whether the address is one the provider will
    # accept is not this package's question - see ``DestinationLinkMissing``.
    link_url: str = ""
    # How the conversation opens, on the goals that open one.
    #
    # The greeting is the owner's and may legitimately be empty - the
    # provider writes its own when none is sent, so an unanswered one is a
    # working ad rather than a refused launch. That is the opposite of
    # ``link_url`` above, and the two must not be read as the same kind of
    # optional: one empty field is a default, the other is a gate.
    #
    # The autofill line is the catalogue's and is never asked for. It is
    # carried rather than looked up again for the reason everything else
    # here is: the launch sequence has no catalogue and must not grow one.
    welcome_text: str = ""
    autofill_text: str = ""
    # The questions the owner kept, if they asked for any. Empty keeps the
    # autofill line above; any at all replace it at the provider.
    welcome_questions: tuple[str, ...] = ()
    # The number the button dials, on the one goal whose button dials.
    #
    # A third optional string beside the two above, and a **third** kind of
    # optional: the address is a gate, the greeting is a default, and this
    # is a gate that also has to be *right*. An address nobody typed stops
    # the launch; a greeting nobody typed is written by the provider; a
    # number nobody typed turns the button into a link, and a number from
    # the wrong country turns it into a button nobody can use.
    #
    # Already in E.164 by the time it arrives - see
    # :mod:`core.targeting.calls`. Stored with the plus and without the
    # ``tel:`` scheme, because the scheme is the provider's spelling of it
    # and belongs where the creative is built.
    phone_number: str = ""
    # The kind of campaign this was built as, resolved: the choice when it
    # belongs to the goal, the goal's default when it does not. Empty only
    # for a goal the table has no rows for.
    campaign_type: str = ""
    # The query appended to ``link_url`` when the advert is served, already
    # checked. Empty on every goal that sends nobody to a website, and on
    # one whose owner cleared it.
    url_tags: str = ""
    # Where a Special Ad Category campaign runs, ISO-3166 alpha-2. Meta asks
    # for it beside the category and otherwise falls back to the account's
    # tax country, which many accounts never set. Empty with no category.
    special_ad_category_countries: tuple[str, ...] = ()
    adjustments: tuple[Adjustment, ...] = ()

    @property
    def needs_lead_form(self) -> bool:
        """Whether the sequence has to create a form and hang it on the ad."""
        return needs_lead_form(self.sends_to)

    @property
    def needs_link(self) -> bool:
        """Whether the advertiser's own address is the thing being bought."""
        return needs_link(self.sends_to)

    @property
    def needs_phone(self) -> bool:
        """Whether the button dials instead of opening anything."""
        return needs_phone(self.sends_to)

    @property
    def shows_a_button(self) -> bool:
        """Whether this ad has anywhere at all to send somebody."""
        return shows_a_button(self.sends_to)

    @property
    def opens_chat(self) -> bool:
        """Whether the button opens a conversation instead of a link."""
        return opens_chat(self.sends_to)

    @property
    def opens_profile(self) -> bool:
        """Whether the button opens the business's Instagram profile."""
        return opens_profile(self.sends_to)
