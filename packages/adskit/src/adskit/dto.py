"""What crosses the boundary between an adapter and the domain."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adskit.refs import (
    AudienceAction,
    AudienceBreadth,
    AudienceSource,
    BreakdownKind,
    Delivery,
    ExternalRef,
    GeoKind,
    LeadStage,
    MinorUnits,
    Ranking,
    TraitKind,
)

_CONFIG = ConfigDict(frozen=True, extra="forbid")


class IssueDTO(BaseModel):
    """One thing the provider says is wrong with an object.

    The first thing a media buyer looks at. A campaign can be ACTIVE,
    funded and spending nothing because of a single row in here, and the
    advertiser's only clue is a figure that does not move.

    ``code`` stays the provider's own number, as a string. It is the only
    part of an issue that is stable enough to match on - the wording
    changes and is translated - and it is a string because nothing promises
    the next provider numbers them.

    ``summary`` is the short sentence and ``message`` the long one. Both
    are the provider's, written for the advertiser, and neither is shown
    without being weighed: a provider's own words are the only thing here
    that can name a fix.
    """

    model_config = _CONFIG

    code: str = ""
    summary: str = ""
    message: str = ""
    level: str = ""
    kind: str = ""


class RecommendationDTO(BaseModel):
    """Something the provider suggests changing. Advice, not a fault.

    Kept apart from :class:`IssueDTO` because the two mean opposite things
    to a decision: an issue is delivery already broken, a recommendation is
    delivery that could be better. Mixing them would produce a screen that
    cries wolf.

    ``importance`` and ``confidence`` are the provider's own words and the
    reason this is worth storing at all - a low-confidence suggestion to
    widen an audience is not something to wake anybody for.
    """

    model_config = _CONFIG

    code: str = ""
    title: str = ""
    message: str = ""
    importance: str = ""
    confidence: str = ""
    blame_field: str = ""


class ReviewFeedbackDTO(BaseModel):
    """Why an ad was refused, in the provider's own words.

    Present only on a rejected ad. Absent everywhere else, which is the
    normal case and not a gap - an ad that was approved has nothing to say
    here.

    Both halves are mappings from a policy name to what the provider says
    about it, because the policies are the provider's list and it grows.
    Modelling them as fields would mean this DTO needed changing every time
    a platform added a rule.

    ``by_placement`` is separate because the same ad can be fine on one
    surface and refused on another, and an advertiser told only "rejected"
    will rewrite the whole ad rather than drop the placement.
    """

    model_config = _CONFIG

    overall: dict[str, str] = Field(default_factory=dict)
    by_placement: dict[str, dict[str, str]] = Field(default_factory=dict)


class CampaignDTO(BaseModel):
    """A campaign as the domain sees it."""

    model_config = _CONFIG

    ref: ExternalRef
    name: str = ""
    status: str = ""
    effective_status: str = ""
    delivery: Delivery = "unknown"
    objective_raw: str = ""
    daily_budget_minor: MinorUnits | None = None
    shared_budget_id: str = ""
    spend_cap_minor: MinorUnits | None = None
    currency: str = ""
    special_ad_categories: tuple[str, ...] = ()
    created_time: datetime | None = None
    issues: tuple[IssueDTO, ...] = ()
    recommendations: tuple[RecommendationDTO, ...] = ()


class AdSetDTO(BaseModel):
    """One ad set: an audience, a budget and a schedule.

    The layer where the money is actually decided, and therefore the layer
    the agent acts on. Every field the guardrails read is here -
    ``learning_status`` above all, because an ad set still learning must be
    left alone whatever the numbers say.
    """

    model_config = _CONFIG

    ref: ExternalRef
    campaign_ref: ExternalRef
    name: str = ""
    status: str = ""
    effective_status: str = ""
    delivery: Delivery = "unknown"
    optimization_goal_raw: str = ""
    billing_event_raw: str = ""
    destination_type_raw: str = ""
    daily_budget_minor: MinorUnits | None = None
    currency: str = ""
    targeting_raw: dict[str, Any] = Field(default_factory=dict)
    promoted_object_raw: dict[str, Any] = Field(default_factory=dict)
    learning_status: str = ""
    is_learning: bool = False
    start_time: datetime | None = None
    end_time: datetime | None = None
    issues: tuple[IssueDTO, ...] = ()
    recommendations: tuple[RecommendationDTO, ...] = ()


class CreativeDTO(BaseModel):
    """The words and the picture an ad was made of, as the provider holds it.

    A mirror of content rather than of delivery, which is what makes it
    different from every other DTO here. There is no ``delivery`` and no
    ``effective_status``: a creative does not run, the ad pointing at it
    does, and copying those two fields across would be two columns that are
    always empty.

    **Read as part of an ad, not as a list of its own.** Every platform
    attaches the creative to the ad in the same answer - Meta as a nested
    expansion, Google as fields on the ad resource - so asking for it
    separately buys nothing and costs a call. That is also why there is no
    ``list_creatives`` port method: the question "what did this ad say" is
    answered by the read that was already happening.

    ``story_raw`` is the provider's own nested block, kept whole. The columns
    beside it are what a screen and an agent read; the block is what a
    rebuild needs, and a creative cannot be edited on Meta at all - changing
    one means building another - so the shape that made this one is the only
    starting point the next one has.
    """

    model_config = _CONFIG

    ref: ExternalRef
    name: str = ""
    status: str = ""
    kind: str = ""

    message: str = ""
    headline: str = ""
    description: str = ""
    link_url: str = ""
    call_to_action: str = ""

    image_hash: str = ""
    video_id: str = ""
    thumbnail_url: str = ""

    page_id: str = ""
    instagram_user_id: str = ""
    post_external_id: str = ""

    story_raw: dict[str, Any] = Field(default_factory=dict)


class AdDTO(BaseModel):
    """One ad: a creative pointed at an audience."""

    model_config = _CONFIG

    ref: ExternalRef
    adset_ref: ExternalRef
    name: str = ""
    status: str = ""
    effective_status: str = ""
    delivery: Delivery = "unknown"
    creative_external_id: str = ""
    creative: "CreativeDTO | None" = None
    lead_form_external_id: str = ""
    issues: tuple[IssueDTO, ...] = ()
    review_feedback: ReviewFeedbackDTO | None = None


class ObjectsDTO(BaseModel):
    """Some campaigns, ad groups and ads of one account, read by their refs.

    The answer to :meth:`~adskit.ports.CampaignControlPort.read_objects`.
    Three lists rather than one because each level has its own DTO, and a
    caller writing them down needs a group's campaign before the group and
    an ad's group before the ad.

    **Only what was asked for, and only what still exists.** A ref the
    provider no longer knows is simply absent - which is what the account
    lists answer for a deleted object too. What is *not* here says nothing
    about the rest of the account.
    """

    model_config = _CONFIG

    campaigns: tuple[CampaignDTO, ...] = ()
    adsets: tuple[AdSetDTO, ...] = ()
    ads: tuple[AdDTO, ...] = ()


class StatusDTO(BaseModel):
    """The answer to "what state is this object in right now"."""

    model_config = _CONFIG

    ref: ExternalRef
    status: str
    effective_status: str = ""
    delivery: Delivery = "unknown"
    learning_status: str = ""
    is_learning: bool = False
    daily_budget_minor: MinorUnits | None = None


class AdPreviewDTO(BaseModel):
    """Where one ad can be seen as the people it is shown to will see it.

    A **frame**, not a picture. Every platform answers this question by
    handing back something to embed rather than an image to save - Meta an
    iframe, Google a shareable link - because the rendering is theirs and
    it changes when their surfaces do. So what crosses this boundary is an
    address and the shape to draw it at.

    ``src`` is an absolute ``https`` address and the adapter is what
    guarantees that. It is going into an ``iframe`` on somebody's screen,
    which makes an unchecked value here the widest hole this package could
    open - and the check belongs on the provider's side of the boundary,
    where the host that is legitimate is known.

    ``width`` and ``height`` are the provider's own suggestion in pixels
    and are nought when it did not make one. Advice rather than
    instruction: a card on a phone is as wide as the phone, and a frame
    told to be 274 wide inside it is a letterbox.

    **Perishable.** No provider documents how long one of these stays
    valid, and both of them sign the address with a token - so the honest
    reading is that it expires without saying when. Nothing here carries a
    timestamp, because the moment that matters is when it was *fetched*,
    which is the caller's clock and not this package's.
    """

    model_config = _CONFIG

    ref: ExternalRef
    ad_format: str
    src: str
    width: int = 0
    height: int = 0


class MetricsDTO(BaseModel):
    """One object's performance on one day.

    ``day`` is in the *ad account's* timezone, because that is the boundary
    the provider aggregated on. Converting it to the advertiser's timezone
    would make our numbers disagree with the provider's own dashboard.
    """

    model_config = _CONFIG

    ref: ExternalRef
    day: date
    campaign_external_id: str = ""
    adset_external_id: str = ""
    ad_external_id: str = ""
    spend_minor: MinorUnits = MinorUnits(0)
    currency: str = ""
    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    leads_reported: int = 0
    results_reported: int = 0
    recallers: int = 0
    attribution_setting: str = ""
    frequency: Decimal = Decimal(0)
    ctr: Decimal = Decimal(0)
    cpm_minor: MinorUnits = MinorUnits(0)
    cpc_minor: MinorUnits = MinorUnits(0)
    quality_ranking: Ranking = ""
    engagement_rate_ranking: Ranking = ""
    conversion_rate_ranking: Ranking = ""

    object_name: str = ""

    unique_clicks: int = 0
    inline_link_clicks: int = 0
    unique_inline_link_clicks: int = 0
    outbound_clicks: int = 0
    landing_page_views: int = 0

    profile_visits: int = 0
    video_plays: int = 0
    video_thruplays: int = 0
    video_p25: int = 0
    video_p50: int = 0
    video_p75: int = 0
    video_p100: int = 0
    video_views_3s: int = 0

    reactions: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0

    cost_per_lead_minor: MinorUnits = MinorUnits(0)
    lead_value_minor: MinorUnits = MinorUnits(0)


class SegmentMetricsDTO(BaseModel):
    """One object's day, for one slice of one cut.

    The same day :class:`MetricsDTO` describes, asked again with the figures
    split by who was reached or where the ad appeared. A separate DTO and not
    a flag on that one, because it is a separate request with a separate
    answer: a provider that is asked for a breakdown stops returning the
    summary row, so the two never arrive together and a single type would be
    one whose fields are half empty depending on how it was fetched.

    **Counts only.** Spend, impressions, reach, clicks and the provider's
    lead count - every one of them a thing that happened, which is what makes
    them addable across the days of a range. The ratios the summary DTO
    carries are deliberately absent: each is arithmetic on these, and a
    stored ratio is the one figure a caller will eventually average across
    days, which is always wrong.

    ``leads_reported`` is the provider's own count and there is no field for
    ours. There cannot be: a lead is a form somebody filled in, and it does
    not come back with an age on it. Every cost per lead computed per segment
    is therefore on the provider's basis - which is a different number from
    the one the rest of this product reasons about, and is why the field
    keeps the ``_reported`` in its name here as well.
    """

    model_config = _CONFIG

    ref: ExternalRef
    day: date
    kind: BreakdownKind
    segment_parts: tuple[str, ...] = ()
    campaign_external_id: str = ""
    adset_external_id: str = ""
    ad_external_id: str = ""
    spend_minor: MinorUnits = MinorUnits(0)
    currency: str = ""
    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    leads_reported: int = 0


FormEndingKind = Literal["", "none", "website", "call", "other"]


class LeadFormDTO(BaseModel):
    """One provider-hosted form, as the provider currently describes it.

    A mirror of a thing this product usually created itself, which makes it
    unlike every other mirror here: the row already exists and the read is
    what keeps it true. Two states it can be in are worth naming.

    A form the advertiser **archived** at the provider is still the form
    every lead it collected came through. Its row is marked, never removed
    - unlike a campaign, whose row is a convenience. This one is the only
    thing that turns a webhook's form id into an owner.

    A form the advertiser **built by hand**, outside this product, collects
    leads all the same. Reading the page's whole list is what gives those
    leads somewhere to land.

    ``is_collecting`` rather than a status vocabulary. Every platform has
    its own set of words for a form that is not taking answers - archived,
    paused, deleted, draft - and the domain only ever acts on the
    distinction between one that collects and one that does not.
    ``status_raw`` carries the provider's own word beside it, for the
    operator comparing against the provider's own screen.
    """

    model_config = _CONFIG

    ref: ExternalRef
    name: str = ""
    is_collecting: bool = False
    status_raw: str = ""
    leads_count: int | None = None
    created_time: datetime | None = None
    questions_raw: tuple[dict[str, Any], ...] = ()
    privacy_policy_url: str = ""
    locale: str = ""
    ending_kind: FormEndingKind = ""
    ending_target: str = ""
    ending_button_text: str = ""


class LeadDTO(BaseModel):
    """One form submission, as the provider hands it over.

    ``field_data`` stays raw: the questions are chosen per form by the
    advertiser, so no fixed set of columns can hold them. Normalisation into
    name/phone/email happens in the domain, which knows the locale rules.
    """

    model_config = _CONFIG

    ref: ExternalRef
    form: ExternalRef | None = None
    field_data: tuple[dict[str, Any], ...] = ()
    submitted_at: datetime | None = None
    campaign_external_id: str = ""
    adset_external_id: str = ""
    ad_external_id: str = ""
    is_organic: bool = False


class InterestDTO(BaseModel):
    """One row of the provider's detailed-targeting catalogue.

    The object that turns a word into something an ad platform will accept.
    A name typed by an owner or written by a model means nothing until the
    provider has answered with an id for it, and every platform makes the
    same distinction - which is why this is a DTO rather than a string.

    **The class name is narrower than what it carries, and deliberately not
    renamed.** Behaviours and life events are the same row at the same rung
    - an id, a name, a size, a path - found by a different call. A second
    class with the identical five fields would be two names for one fact,
    and renaming this one would churn every caller to say something
    :attr:`kind` already says.

    The size is a **range**, and stays one. Meta answers with a lower and an
    upper bound because it does not know the figure either; collapsing them
    into one number here would invent a precision that the screen would then
    show to somebody making a budget decision. Zero means the provider did
    not say - not that nobody is there.
    """

    model_config = _CONFIG

    ref: ExternalRef
    name: str
    kind: TraitKind = "interest"
    audience_lower: int = 0
    audience_upper: int = 0
    path: tuple[str, ...] = ()


class RetiredOptionDTO(BaseModel):
    """A detailed-targeting option the provider has withdrawn, and what it
    offers instead.

    Providers merge and retire catalogue entries without warning and
    without a broadcast. The search index goes on returning the old entry
    long afterwards, so nothing before the ad set is created can tell that
    an id is dead - the refusal is the announcement.

    **The replacement is why this crosses the boundary** rather than
    staying in a log line. A refusal naming only what is wrong leaves an
    owner with a campaign that cannot be created and no way to find out
    which of twelve words is the dead one; a refusal carrying the mapping
    is a campaign that fixes itself.

    ``alternative_id`` is empty when the provider withdrew an option and
    offered nothing in its place, which is a real answer: the option goes,
    and nothing takes its seat.
    """

    model_config = _CONFIG

    retired_id: str
    retired_name: str = ""
    alternative_id: str = ""
    alternative_name: str = ""


class LocationDTO(BaseModel):
    """One place in the provider's geography catalogue.

    The same bargain as :class:`InterestDTO`, for the other half of a
    targeting spec: an owner thinks "Toshkent" and every platform targets a
    key it issued itself. Meta calls this one ``2420901`` and Google calls
    it ``1010342``; neither will accept the word.

    Which is also why nothing here is ever hardcoded. Providers merge and
    retire geography rows the same way they do interests, and a key written
    into a catalogue file fails silently - the ad set is created, accepted,
    and delivers to somewhere else.

    ``context`` is what makes a list of results choosable. "Toshkent" is
    both a city and the region around it, and a person picking from two rows
    with the same word on them is guessing.

    ``supports_radius`` is the field the screen branches on. A radius around
    a city means something; a radius around a region does not, and offering
    the control anyway produces a number the provider discards without
    saying so.
    """

    model_config = _CONFIG

    ref: ExternalRef
    name: str
    kind: GeoKind = "other"
    country_code: str = ""
    context: str = ""
    parent_id: str = ""
    supports_radius: bool = False


class ReachDTO(BaseModel):
    """How many people a targeting spec would reach, as a range.

    The number that turns "we narrowed your audience" into something an
    owner can judge. A range rather than a figure, for the same reason
    :class:`InterestDTO` carries one: the provider does not know either.

    ``ready`` is not decoration. Providers answer the question before they
    have finished computing it, and a zero that means "not yet" shown as a
    zero that means "nobody" is the difference between a person waiting a
    minute and a person widening an audience that was never narrow.

    ``available`` is the third state, and it is not the same as either. A
    provider can answer that this particular spec cannot be sized at all -
    Meta stops estimating as soon as a customer-file audience with more
    than one key is named, and says so by returning ``-1``. Waiting does
    not help and asking again will not either, so a caller has to be able
    to tell "not yet" from "not ever" rather than treating both as a zero.
    """

    model_config = _CONFIG

    lower: int = 0
    upper: int = 0
    ready: bool = True
    available: bool = True


class AudienceStateDTO(BaseModel):
    """What a provider says about an audience it is still working on.

    Two of these hang off :class:`AudienceDTO` and they answer different
    questions - whether the last write finished, and whether the result may
    be advertised to. Both are the provider's own code with the provider's
    own sentence beside it, and neither is enumerated here.

    Not enumerating is a decision, and the same one :class:`LeadFormDTO`
    made about a form's status. The full set of codes is not published: the
    two that are documented mean "ready" and "disabled", and the rest are
    discovered by meeting them. A table written from the two known values
    would classify everything else as a failure, and the honest reading of
    an unfamiliar code is "not ready yet", not "broken".

    ``code`` is a string although every provider seen so far sends a
    number, for the reason every other id here is one: nothing promises the
    next one does.
    """

    model_config = _CONFIG

    code: str = ""
    description: str = ""


class AudienceDTO(BaseModel):
    """One saved audience an advertiser owns, held by the provider.

    Not part of the campaign hierarchy and deliberately not modelled as
    though it were. It belongs to the ad account, several ad sets point at
    it by id, and it outlives every one of them - which is why it has a
    port of its own rather than a place in the targeting spec beside an
    interest.

    **Never holds a person.** What was uploaded into it cannot be read back
    from any provider, by design: the whole exchange is one-way. So the
    only thing this DTO can say about the people in it is how many the
    provider thinks there are, and it says even that as a range.

    ``subtype_raw`` is the provider's own word for where the audience came
    from - a customer file, site traffic, a seed audience - and it stays
    raw. A domain vocabulary for it is not invented here: this block builds
    exactly one kind, and a classification drawn from one example would be
    shaped like that example. What the domain does need today is the one
    question below.
    """

    model_config = _CONFIG

    ref: ExternalRef
    name: str = ""
    description: str = ""
    subtype_raw: str = ""
    accepts_members: bool = False

    can_seed: bool = True

    approximate_count_lower: int = 0
    approximate_count_upper: int = 0

    processing: AudienceStateDTO = Field(default_factory=AudienceStateDTO)
    readiness: AudienceStateDTO = Field(default_factory=AudienceStateDTO)
    is_ready: bool = False

    customer_file_source: str = ""

    rule_raw: dict[str, Any] = Field(default_factory=dict)
    lookalike_raw: dict[str, Any] = Field(default_factory=dict)
    retention_days: int = 0

    created_time: datetime | None = None
    updated_time: datetime | None = None


class AudienceRuleDTO(BaseModel):
    """What an audience should be built out of, when nobody is uploaded into it.

    The other way to make an audience, and the opposite of a customer list
    in every way that matters. There is **no personal data here at all**:
    the provider already knows who did what on its own surfaces, so all
    that crosses is a rule - which thing, what people did with it, and how
    far back to look. Nothing about a person is collected, hashed or sent.

    Four fields, and every one of them is the domain's own word. The
    provider's spelling of them - ``lead`` rather than ``lead_form``,
    ``lead_generation_submitted`` rather than ``submitted``, an envelope of
    inclusions and retention seconds - stops at the adapter, exactly as a
    currency's offset does and as a customer list's column names do. That
    is the whole reason this is four fields instead of a ``dict``: a rule
    document passed through transparently would be Meta's JSON travelling
    under a neutral name, and the second provider would have to parse it to
    find out it could not use it.

    ``source`` is the ref of the thing itself - the pixel, the page, the
    lead form - so it carries which provider issued the id. A rule built
    against one provider's page id and sent to another is a mistake the
    type makes impossible.

    **Not every pair is offered.** Which actions a source supports, and how
    far back each can look, is the provider's answer and is asked for
    through :meth:`~adskit.ports.AudienceSourcePort.supported_rules`. A
    pair nobody offers is refused with both halves named, which is more
    use than a type error naming neither.

    **An action that subtracts is still one action.** "Came and did not
    buy" is a single thing a business asks for, and it stays a single
    ``action`` here - the adapter is what knows its provider expresses that
    as two blocks in one document. The alternative, a second optional
    action field, would put the subtraction in the domain object and from
    there on every screen that renders one: a picker with two dropdowns and
    the word "except" between them is the vocabulary this product exists to
    avoid.

    What is deliberately absent: **video**. Every platform builds audiences
    from who watched one, and the shape is not something to guess at - see
    the note in the adapter that would have to spell it.
    """

    model_config = _CONFIG

    kind: AudienceSource
    action: AudienceAction
    source: ExternalRef
    retention_days: int


class RuleSupportDTO(BaseModel):
    """What one provider will actually build out of one kind of source.

    A static answer - no account, no token, no call. It exists so a form
    can be drawn before anybody presses anything: the choices offered have
    to be the choices the provider accepts, and discovering the difference
    at creation time means a person filling in a form to be told no.

    ``max_retention_days`` differs per source on every platform seen so
    far, and the differences are large: what a website may look back is not
    what a lead form may. A single number here would be wrong for two of
    the three, in the direction that produces a refusal.
    """

    model_config = _CONFIG

    kind: AudienceSource
    actions: tuple[AudienceAction, ...] = ()
    max_retention_days: int = 0


class LookalikeSpecDTO(BaseModel):
    """What a new audience should be built to resemble, and where.

    The third way to make one, after a customer list and a rule, and the
    only one whose input is **another audience**. Nothing about a person is
    collected, hashed or sent here either: the seed already exists on the
    provider, and what crosses is its id, how wide to cast and which
    country to cast in.

    Three fields, and the absence of a fourth is the design. There is no
    percentage: see :data:`~adskit.refs.AudienceBreadth` for why a number
    that only one platform has would not survive the second.

    ``origin`` is the ref of the seed, so it carries which provider issued
    the id. Building against one provider's audience id and sending it to
    another is a mistake the type makes impossible - and unlike a pixel or
    a page, an audience id looks exactly like every other audience id, so
    nothing else would have caught it.

    ``country`` is one country and is required. Every platform builds a
    lookalike inside one country's population, because the whole operation
    is "the top few per cent of *somewhere*" - and a provider that takes a
    list of them takes it as a list of separate audiences. Advertising in
    two countries means two of these.

    **The seed has to be big enough, and this DTO cannot say whether it
    is.** Providers ask for a hundred people *in the chosen country*, which
    is not a figure any of them will report: the size that comes back is a
    total. So the check that can be made from this side is that the seed is
    usable at all, and the one that cannot is left to arrive as the
    provider's own refusal.
    """

    model_config = _CONFIG

    origin: ExternalRef
    breadth: AudienceBreadth
    country: str


DIGEST_LENGTH: Final = 64
_HEX = frozenset("0123456789abcdef")


class AudienceMemberDTO(BaseModel):
    """One person in a customer list, as digests and nothing else.

    **This is the boundary that keeps personal data out of the provider
    packages, and it is enforced rather than documented.** Every field is
    validated as a SHA-256 digest in lower-case hex, so an email address or
    a phone number cannot be put in one of them: constructing this DTO with
    a plaintext value raises. An adapter therefore cannot leak what it was
    never able to receive, and the test that says so rests on the type
    rather than on a review of one function.

    Producing the digests is the domain's job and happens above this
    package - it needs a phone-number parser and a locale, and this package
    has neither. What travels here is the finished result.

    Every field is optional and empty means "not collected". Providers hash
    each key independently and match on whatever is present, so a list of
    email addresses alone is a perfectly ordinary upload; the more keys
    that are filled, the more people are matched.

    The keys are the domain's names. A provider's own spelling for them -
    ``EMAIL``, ``FN``, ``hashed_phone_number`` - belongs to the adapter,
    exactly as a currency's offset does.
    """

    model_config = _CONFIG

    email: str = ""
    phone: str = ""
    first_name: str = ""
    last_name: str = ""
    city: str = ""
    country: str = ""

    @field_validator("*")
    @classmethod
    def _is_a_digest(cls, value: str) -> str:
        """Refuse anything that is not already hashed."""
        if not value:
            return value
        if len(value) != DIGEST_LENGTH or not set(value) <= _HEX:
            raise ValueError(
                "must be a SHA-256 digest in lower-case hex; "
                "personal data is hashed before it reaches this package"
            )
        return value

    @property
    def is_empty(self) -> bool:
        """Whether this row would identify nobody. Not worth uploading."""
        return not any(
            (
                self.email,
                self.phone,
                self.first_name,
                self.last_name,
                self.city,
                self.country,
            )
        )


class MemberUploadDTO(BaseModel):
    """How much of one customer list the provider took.

    Not an :class:`ActionResult`, and the difference is the point. That one
    answers "did the write land, and what did the provider silently remove
    from it" - a diff between two documents. This answers "how many of
    these rows were accepted", which is a count, and the provider states it
    explicitly rather than dropping anything quietly. Putting a count in
    ``applied`` and a refusal in ``dropped`` would reuse two fields for a
    meaning they were given for something else.

    pydantic rather than a dataclass for the reason stated at the top of
    this module: these numbers are parsed out of a body somebody else
    controls.

    ``invalid`` is the figure that matters and the one nobody looks at. A
    normalisation rule applied wrongly does not fail - it produces rows the
    provider accepts the shape of and matches to nobody - so an upload that
    reports thousands received and thousands invalid is the only warning
    there is going to be.

    **A removal answers in this shape too**, which is why the name says
    upload and the fields do not. Providers reply to "take these people
    out" with the same two counts they reply to "put these people in"
    with, and a second DTO holding the same two integers would be two
    names for one fact. ``received`` reads as "rows the provider accepted
    from us" in both directions.
    """

    model_config = _CONFIG

    ref: ExternalRef
    received: int = 0
    invalid: int = 0
    session_id: str = ""
    invalid_samples: dict[str, str] = Field(default_factory=dict)
    dry_run: bool = True


class LeadEventDTO(BaseModel):
    """What became of one lead, on its way back to the provider.

    The only object in this package that travels **towards** a provider
    carrying something the provider did not tell us first, and the whole of
    what makes a cost per qualified lead act on anything. Without it this
    product measures CPQL and the platform optimises CPL, which are two
    machines pulling in opposite directions on the same budget.

    **No personal data, ever, and the shape is what guarantees it.** The
    lead is named by the id the provider issued when it handed the person
    over - not by a telephone number, not by a hash of one. That is a
    deliberate difference from :class:`AudienceMemberDTO` next door, which
    carries digests because a customer list is matched on who somebody is;
    here the provider already knows who this is and is only being told how
    it went. Nothing in this class can hold a name.

    ``event_id`` is the caller's idempotency key and is required. Every
    platform de-duplicates on one, and the retry that this product will
    perform - a sweep, running again tomorrow over anything unacknowledged -
    is exactly the traffic that needs it: the same verdict sent twice must
    count once, or an account's own reporting drifts upwards every time a
    worker is restarted.

    ``value_minor`` and ``currency`` travel only with ``"converted"`` and
    are refused on the other two. A qualified lead has no amount attached -
    nobody has been billed yet - and a nought sent beside one is not "no
    value", it is a sale of nothing, which is a figure the provider will
    happily optimise towards.
    """

    model_config = _CONFIG

    lead: ExternalRef
    stage: LeadStage
    occurred_at: datetime
    event_id: str
    value_minor: MinorUnits | None = None
    currency: str = ""

    @field_validator("event_id")
    @classmethod
    def _has_an_idempotency_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("event_id is required: a retry without one double-counts")
        return value

    @model_validator(mode="after")
    def _only_a_sale_carries_money(self) -> "LeadEventDTO":
        """Money on a stage that has not produced any is refused here."""
        if self.stage != "converted" and self.value_minor is not None:
            raise ValueError(f"{self.stage!r} carries no amount; only a sale does")
        if self.value_minor is not None and not self.currency:
            raise ValueError("an amount without a currency is not an amount")
        return self


class ConversionReceiptDTO(BaseModel):
    """How much of one batch of verdicts the provider took.

    Deliberately not an :class:`ActionResult`. That one answers "did the
    write land, and what did the provider silently remove from it", which is
    a diff between two documents; this is a count, and it is the same shape
    :class:`MemberUploadDTO` answers an upload in for the same reason.

    A second class rather than reusing that one, because the two are read
    by different people asking different questions. That one is about
    personal data leaving and carries a session and refusal samples; this
    one is about a number the account's own reporting is built on, and its
    important field is ``accepted``.

    ``accepted`` is what the provider says it received - never what was
    sent. The two differ whenever a lead id has aged out of the provider's
    own retention, and a caller that assumed the first meant the second
    would mark a verdict reported that nothing ever heard.
    """

    model_config = _CONFIG

    dataset: ExternalRef
    accepted: int = 0
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class ActionResult:
    """The outcome of one write."""

    ok: bool
    ref: ExternalRef
    applied: dict[str, Any] = field(default_factory=dict)
    dropped: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    raw_response: dict[str, Any] = field(default_factory=dict)


class GrantDTO(BaseModel):
    """What a person's consent was traded for: a token and what it may do.

    The provider's own word for the person who approved travels with it,
    because the connect callback is the one moment it is known for certain
    and some rules - one advertiser identity per cabinet - are about that
    person rather than about the account they reach.

    ``expires_in`` is seconds from now, not a date: a port has no clock, so
    the caller that has one turns it into a moment. Zero means the provider
    named no end.
    """

    model_config = _CONFIG

    token: str = Field(repr=False)
    expires_in: int = 0
    scopes: tuple[str, ...] = ()
    external_user_id: str = ""


class PeopleCountDTO(BaseModel):
    """How many people one object reached over a whole range.

    Its own DTO because it is its own question. A day's reach and a
    week's reach are different numbers that cannot be derived from each
    other: somebody who saw the ad on Monday and again on Friday is two
    people in the daily rows and one person in the week. Only the provider
    knows who the people were, so a range's count has to be asked of it
    for that range - and summing :class:`MetricsDTO` rows instead is the
    overcount this exists to avoid.

    ``since`` and ``until`` are inclusive and in the ad account's own
    timezone, the same axis as :attr:`MetricsDTO.day`.
    """

    model_config = _CONFIG

    ref: ExternalRef
    since: date
    until: date
    campaign_external_id: str = ""
    adset_external_id: str = ""
    ad_external_id: str = ""
    reach: int = 0
    recallers: int = 0
