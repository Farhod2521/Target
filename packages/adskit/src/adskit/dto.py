"""What crosses the boundary between an adapter and the domain.

Named in domain terms, never provider terms: a field called
``objective_raw`` is honest about carrying Meta's vocabulary, and a field
called ``leads`` means leads on any platform.

pydantic rather than dataclasses, because these are parsed from JSON that
somebody else controls, and a shape change should fail here with a readable
error rather than three layers up as an ``AttributeError``.

The exception is :class:`ActionResult`, which nobody parses: an adapter
constructs it from a call it just made. It stays a dataclass.
"""

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

# Frozen for the same reason ExternalRef is: a DTO edited on the far side of
# a boundary is a bug that reads like a feature.
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
    # Which rung the issue is really about. An ad set's list can carry an
    # issue whose cause is the campaign above it, and acting on the wrong
    # object is the failure this field prevents.
    level: str = ""
    # The provider's own classification, kept raw. Empty where it sent none.
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
    # The field the provider blames, in its own vocabulary.
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
    # What we asked for, and what is actually happening. A campaign can be
    # ACTIVE while every ad set under it is paused, so both are carried.
    status: str = ""
    effective_status: str = ""
    # The adapter's reading of effective_status in domain words. Stored
    # beside the raw value rather than instead of it: the raw one is what
    # an operator compares against the provider's own dashboard.
    delivery: Delivery = "unknown"
    # Provider vocabulary, kept raw and named as such. The domain stores it
    # for display and never branches on it.
    objective_raw: str = ""
    daily_budget_minor: MinorUnits | None = None
    # The provider's id of a budget other campaigns draw on as well, so a
    # change to it is a change to all of them. Empty when the budget is
    # this campaign's own, which is every budget a platform without shared
    # budgets has.
    shared_budget_id: str = ""
    # The most this campaign may spend in total before the provider stops
    # it. A different question from the daily budget and answered by every
    # large platform: one is a rate and this is a ceiling.
    #
    # ``None`` means no cap rather than a cap of nothing. A campaign that
    # may spend zero in total is a campaign that cannot run, and the two
    # readings are the difference between a screen saying "no limit" and
    # one saying "stopped".
    spend_cap_minor: MinorUnits | None = None
    currency: str = ""
    # Housing, employment and credit ads are restricted on every large
    # platform, and the restriction follows the campaign. Carried because
    # anything created underneath has to inherit it.
    special_ad_categories: tuple[str, ...] = ()
    created_time: datetime | None = None
    # What the provider says is wrong, and what it suggests. Empty is the
    # ordinary answer for a campaign that is simply working.
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
    # The parent, as a ref rather than an id: the mirror has to attach this
    # row to a campaign it may or may not have seen yet.
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
    # Opaque on purpose, in the provider's own shape - the same dict
    # AudiencePort.apply takes. An AudienceIntent abstraction invented from
    # one provider would be shaped exactly like that provider.
    targeting_raw: dict[str, Any] = Field(default_factory=dict)
    promoted_object_raw: dict[str, Any] = Field(default_factory=dict)
    # Empty where the provider has no such concept, or where it has not
    # said yet. Kept raw for the screen and for an operator comparing
    # against the provider's own dashboard.
    learning_status: str = ""
    # The same fact as a decision the guardrail can act on. A boolean and
    # not a string comparison, because the alternative is every caller
    # knowing which of a provider's several learning values mean "leave
    # this alone" - and that knowledge belongs in the adapter.
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
    # The provider's own word, unmapped. Meta answers ACTIVE, IN_PROCESS,
    # WITH_ISSUES or DELETED here and none of them describes delivery.
    status: str = ""
    # Which shape the content took: ``link``, ``video``, ``post``, or empty
    # for a shape this product does not build. Not the provider's word -
    # both Meta blocks are named after the *field* they live under - but
    # the distinction is real everywhere and an agent comparing a video
    # against a still needs it as a column rather than as a guess about
    # which of two other fields is filled.
    kind: str = ""

    message: str = ""
    headline: str = ""
    description: str = ""
    link_url: str = ""
    # The button, in the provider's vocabulary. There is no domain word for
    # it: the list is the provider's and the advertiser picked from it.
    call_to_action: str = ""

    # Exactly one of these two is set, and which one is what ``kind`` says.
    # An image is named by a hash and a video by an id - Meta's own
    # asymmetry, and the single detail most likely to be got wrong.
    image_hash: str = ""
    video_id: str = ""
    thumbnail_url: str = ""

    # Who the ad ran as. Plain ids and not refs: a page belongs to a
    # different part of the domain and is synced by a different job.
    page_id: str = ""
    # The provider renamed this field. Meta called it ``instagram_actor_id``
    # until v22.0 and retired that name for every version on 2025-09-09; the
    # word here follows the provider's current one, because a DTO named
    # after a dead field is how the rename gets half-done.
    instagram_user_id: str = ""
    # Set when the creative promotes a post that already existed. Its words
    # live on the post, so the text fields above are empty and that is the
    # truth rather than a parse that missed.
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
    # The creative's content, when the provider sent it with the ad. Kept
    # beside the id above rather than instead of it: the id is what the ad
    # row stores and what survives a creative nothing mirrored, and this is
    # what fills that mirror.
    #
    # ``None`` means the provider did not answer with one, which happens on
    # a read that did not ask - not that the ad has no creative.
    creative: "CreativeDTO | None" = None
    # Plain id, not a ref: the form belongs to a different part of the
    # domain and may not have been synced when the ad is. Empty for every
    # ad that does not collect leads.
    lead_form_external_id: str = ""
    issues: tuple[IssueDTO, ...] = ()
    # No recommendations here. Providers give advice about audiences and
    # budgets, which are decided one level up; an ad has neither.
    #
    # ``None`` rather than an empty DTO, because "the ad was approved" and
    # "the ad was refused and the provider listed nothing" are different
    # answers and the second one is a bug worth seeing.
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
    # The one field above, in words the product can show. Here rather than
    # derived by the caller for the same reason it is on every other DTO:
    # translating a provider's status vocabulary is the adapter's job, and
    # a second caller doing it themselves is the first place the two answers
    # can disagree.
    delivery: Delivery = "unknown"
    # Meta calls it learning_stage_info; Google has its own version. Empty
    # when the provider has no such concept. The guardrail reads it.
    learning_status: str = ""
    is_learning: bool = False
    # What this object is set to spend per day, or ``None`` when it holds no
    # budget of its own - a campaign whose ad sets each carry theirs. Read
    # here because a budget change is decided against the current figure and
    # this is the call that was going to be made anyway; asking separately
    # would be a second call to learn something already on the wire.
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

    # The ad or the creative this shows, whichever was asked about.
    ref: ExternalRef
    # Which surface it is drawn for, in the provider's own vocabulary -
    # Meta's ``MOBILE_FEED_STANDARD`` and its seventy-odd siblings. There
    # is no domain word for it and inventing one would be inventing a
    # mapping: the list is the provider's, the supported combinations are
    # the provider's, and a name of our own would have to be kept in step
    # with both.
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
    # Where this row sits, as plain ids rather than refs - the same choice
    # :class:`LeadDTO` makes and for the same reason: the mirror tables may
    # not have caught up, and a figure that cannot be stored until its
    # parent has been synced is a figure that goes missing on the day it
    # matters. The row's own level decides which of the three repeats
    # ``ref.id``.
    campaign_external_id: str = ""
    adset_external_id: str = ""
    ad_external_id: str = ""
    spend_minor: MinorUnits = MinorUnits(0)
    # The **ad account's** currency, not the advertiser's. Meta bills in one
    # and the owner may think in another, and converting here would be
    # inventing an exchange rate this package has no source for.
    currency: str = ""
    impressions: int = 0
    # People, not impressions, and **not additive**. Two ad sets reaching
    # the same person report that person twice, so a total summed from rows
    # is an overcount the provider would never print. Carried because it is
    # in the same answer and because judging creative fatigue needs it;
    # anything showing a total has to ask the provider for one.
    reach: int = 0
    clicks: int = 0
    # The provider's own lead count. Ours may differ - a dropped webhook, a
    # test submission - and the difference is worth showing, not hiding.
    leads_reported: int = 0
    # The provider's count of a result this product holds no table for: a
    # conversation started on the platform's own surface, a confirmed
    # telephone call.
    #
    # **Its own field and never folded into the lead count.** Both are "a
    # result" and they are not the same object - a lead has a name and a
    # telephone number here and can be marked qualified, while these happen
    # somewhere nothing here reads. Added together they would put a number
    # into the cost per lead with no lead behind it, which is the one error
    # this product cannot afford to make.
    #
    # Nought on a form campaign, which reports its result as a lead.
    results_reported: int = 0
    # How many people the provider estimates would remember the advert. The
    # result of an awareness campaign, and nought on every other kind.
    recallers: int = 0
    # The account's own attribution window, **and only where it differs**
    # from the one this product asked for.
    #
    # Not a figure: it is what makes the figures beside it checkable. Every
    # request names its own window, so an account set to a different one in
    # the provider's console reports a different lead count for the same
    # day - for ever, with nothing on either screen to explain it.
    #
    # Empty is the ordinary answer and means the two agree. The comparison
    # is the adapter's because it is the only layer that knows what was
    # asked for; a raw setting here would be a provider's vocabulary
    # crossing the boundary to ask a question the boundary already answered.
    attribution_setting: str = ""
    # Ratios the provider computed, kept as it sent them so a single row can
    # be checked against its dashboard. Also not additive: a period's CTR is
    # its clicks over its impressions, never the mean of its days.
    frequency: Decimal = Decimal(0)
    ctr: Decimal = Decimal(0)
    cpm_minor: MinorUnits = MinorUnits(0)
    cpc_minor: MinorUnits = MinorUnits(0)
    # How this ad compares with the ads it competes against, as of this
    # day. Three verdicts and not one, because they fail differently: a
    # tired image, an audience that scrolls past, and a landing page nobody
    # converts on are three different things to fix.
    #
    # Only the ad level carries them - they are a judgement about a
    # creative, and a campaign is not one - so every other row here has the
    # empty string. Kept per day rather than as a current state: the
    # verdict moves, and the direction it moves in is the only warning
    # this product gets that a creative is wearing out.
    quality_ranking: Ranking = ""
    engagement_rate_ranking: Ranking = ""
    conversion_rate_ranking: Ranking = ""

    # What the object was called on this day.
    #
    # Not a duplicate of the mirror's name, which holds what it is called
    # now. The two differ for a renamed object and, more importantly, the
    # mirror has no row at all for one that was deleted - a provider hands
    # out no tombstones, so the mirror shrinks and the figures stay. This
    # is what keeps a ninety-day report from listing spend against a bare
    # id nobody can identify.
    object_name: str = ""

    # What the click actually was.
    #
    # ``clicks`` counts every click on the unit, including the ones that
    # expanded the caption. ``inline_link_clicks`` counts the ones that
    # went where the money was being spent to send them, and
    # ``outbound_clicks`` the ones that left the platform entirely. An ad
    # whose ``ctr`` is healthy and whose link clicks are not is an ad being
    # poked at rather than acted on.
    #
    # The ``unique_`` pair counts **people**, so - like ``reach`` - they do
    # not add up across rows.
    unique_clicks: int = 0
    inline_link_clicks: int = 0
    unique_inline_link_clicks: int = 0
    outbound_clicks: int = 0
    # People whose browser loaded the page the advert sent them to. Below
    # ``inline_link_clicks`` by whatever the site lost on the way, and
    # nought wherever the provider has no tag on that page to count with.
    landing_page_views: int = 0

    # How far into the video people got, and the only read on a creative
    # that does not wait for somebody to click. Zero on every image ad,
    # which is the ordinary case and not a gap.
    #
    # ``video_plays`` is a start and ``video_thruplays`` is Meta's word for
    # watched-to-the-end-or-fifteen-seconds. The quartiles are what turn a
    # single ratio into a shape: an ad that loses everybody at a quarter is
    # a different problem from one that loses them at three quarters.
    # Visits to the Instagram profile, Meta's count. The whole result of
    # an ad set bought for them and nought on every other.
    profile_visits: int = 0
    video_plays: int = 0
    video_thruplays: int = 0
    video_p25: int = 0
    video_p50: int = 0
    video_p75: int = 0
    video_p100: int = 0
    # Views of at least three seconds. Not ``video_plays``, which counts a
    # video that merely started on screen: this is the viewer who stayed,
    # and over impressions it is how often the opening stops the scroll.
    video_views_3s: int = 0

    # What people did with the post itself.
    #
    # The one "did they like it" signal the owner of a shop reads without
    # being taught, and the only one that arrives without money being spent
    # on a click. A comment is also a job rather than a figure: somebody
    # asked a question in public and nobody has answered it.
    #
    # Counts of actions, so they add up across days and across the ads
    # showing one creative - unlike ``reach``, which counts people.
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0

    # The provider's own cost per lead, kept beside our own arithmetic for
    # the same reason ``ctr`` and ``cpm`` are: so one row can be checked
    # against the provider's dashboard. Ours is spend over leads and can
    # differ - a lead that arrived either side of midnight, an attribution
    # window closing - and the difference is worth seeing rather than
    # hiding.
    cost_per_lead_minor: MinorUnits = MinorUnits(0)
    # What the provider says those leads were worth. Zero unless the
    # advertiser sends conversion values back, which most lead campaigns do
    # not - the revenue this product actually reasons about arrives from
    # the advertiser marking a sale, not from here.
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
    # The slice, still in pieces: ``("25-34", "female")``.
    #
    # Not joined here, and the reason is a layering rule rather than taste.
    # How the parts become one stored value - the separator, what an empty
    # half becomes - is a domain decision and lives in exactly one place in
    # the domain. This package must not import that place, so it hands the
    # parts over in order and lets the caller join them.
    #
    # A tuple rather than two fields, because cuts do not all have two
    # dimensions: a device cut has one and a placement-by-hour cut would
    # have three.
    segment_parts: tuple[str, ...] = ()
    campaign_external_id: str = ""
    adset_external_id: str = ""
    ad_external_id: str = ""
    spend_minor: MinorUnits = MinorUnits(0)
    currency: str = ""
    impressions: int = 0
    # People, and **not additive** - across days or across slices. Somebody
    # who saw the ad in two placements is one person and two rows.
    reach: int = 0
    clicks: int = 0
    leads_reported: int = 0


# What a form's last screen offers, whatever the provider calls it.
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
    # The provider's own total for this form. ``None`` when it did not say,
    # which is a different answer from zero: zero means nobody has filled
    # this form in and there is nothing to go looking for.
    leads_count: int | None = None
    created_time: datetime | None = None
    # As the provider holds them, not as they were asked for. The two drift
    # the moment a form is made anywhere but here, and a year later the
    # honest answer to "what was this person asked" is the provider's copy.
    questions_raw: tuple[dict[str, Any], ...] = ()
    privacy_policy_url: str = ""
    locale: str = ""
    # What the screen after the form offers, in the domain's words: no
    # button, a link out, a call, or a button this product does not build.
    # Empty when the provider did not say. ``ending_target`` is the address
    # or the number behind the button.
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
    # ``None`` when the provider did not say. Not defaulted to now: a port
    # holds no clock, and a lead stamped with the moment a worker happened
    # to reach it is a lead that arrived at the wrong time forever. The
    # caller has a clock and decides what to fall back to.
    submitted_at: datetime | None = None
    # Attribution. Kept as plain ids rather than refs because the mirror
    # tables may not have caught up when the lead arrives.
    campaign_external_id: str = ""
    adset_external_id: str = ""
    ad_external_id: str = ""
    # The provider's own claim that nobody paid for this one - somebody
    # found the form rather than being shown an ad. Carried because it
    # changes what a cost-per-lead means, and kept separate from "this is a
    # test submission", which no provider reports reliably.
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
    # Which of the three kinds of row this is. Defaulted: a caller that
    # does not say means an interest.
    #
    # Load-bearing above this package: a targeting spec files the three
    # under different keys, and a behaviour written into the interests block
    # is not refused - it is accepted, matched against nobody, and delivered
    # as though the audience were narrower than anybody chose.
    kind: TraitKind = "interest"
    audience_lower: int = 0
    audience_upper: int = 0
    # Where the provider files it: ("Interests", "Food and drink", "Coffee").
    # Two catalogue entries share a name often enough that a person choosing
    # between them needs this, and it costs one field to carry.
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
    # ISO-3166 alpha-2, as the provider reported it. Carried rather than
    # inferred: the search is asked in one country and answers in several.
    country_code: str = ""
    # What contains it - a region for a city, a country for a region.
    context: str = ""
    # The provider's key for the region a city lies in, empty when it did
    # not say. What tells a caller that a city and a region it also chose
    # are the same ground twice - the provider refuses that pair, and the
    # name in ``context`` is not a key anything can be compared against.
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
    # The provider's own sentence, written for the advertiser. Shown rather
    # than translated: it is the only text in this DTO that can name what
    # is actually wrong with a particular audience.
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
    # Whether this product may add people to it. The one question the
    # domain asks of ``subtype_raw``, in the same bargain
    # ``LeadFormDTO.is_collecting`` strikes: the provider's whole
    # vocabulary stops at the adapter and a single fact crosses.
    #
    # False for everything the provider fills in itself - site visitors,
    # people who engaged, a lookalike built from a seed. An unfamiliar
    # subtype reads as False, which is the safe direction: the cost is an
    # upload button that does not appear, against personal data posted to
    # an audience that was never meant to receive any.
    accepts_members: bool = False

    # Whether a new audience may be built to resemble this one. The second
    # question the domain asks of ``subtype_raw``, and it is not the
    # negation of the one above: an audience the provider fills itself
    # takes no upload and is a perfectly good seed.
    #
    # False for one thing only - an audience that is already a lookalike.
    # No provider documents building one from another, and the honest
    # reading of an undocumented combination is that it is not offered.
    #
    # An unfamiliar subtype reads as True here, which is the opposite
    # direction from ``accepts_members`` above and for a reason that does
    # not apply to it: nothing personal is sent either way, so the cost of
    # a wrong True is one refused call that names itself, while the cost of
    # a wrong False is a row missing from a picker with nothing to explain
    # it.
    can_seed: bool = True

    # How many people the provider thinks are in it, as a range.
    #
    # A range because that is what is answered: providers stopped giving a
    # single figure for exactly the reason this DTO would have had to
    # invent one. Zero for both means "not said yet", which is the ordinary
    # answer for hours after an upload and is not the same as an empty
    # audience - a distinction the screen has to keep, because the two lead
    # to opposite advice.
    approximate_count_lower: int = 0
    approximate_count_upper: int = 0

    # Whether the last write has finished, and whether the result can be
    # advertised to. Two states and not one: an audience can be perfectly
    # usable while an upload into it is still being processed, and a
    # finished upload can still produce something too small to deliver.
    processing: AudienceStateDTO = Field(default_factory=AudienceStateDTO)
    readiness: AudienceStateDTO = Field(default_factory=AudienceStateDTO)
    # The one question a launch screen asks. Derived by the adapter from
    # ``readiness`` because reading a provider's status vocabulary is the
    # adapter's job everywhere else in this package too.
    is_ready: bool = False

    # Where the advertiser says the data came from, in the provider's own
    # vocabulary. Carried because it is not decoration: platforms require
    # it on a customer file and store it as part of the representation the
    # advertiser made about their own data.
    customer_file_source: str = ""

    # The provider's own rule document, whole and unread.
    #
    # Carried raw rather than parsed back into :class:`AudienceRuleDTO`,
    # and the asymmetry is deliberate. Going out, the domain says what it
    # wants and the adapter spells it. Coming back, most of these were
    # built in the provider's own console by somebody using its whole
    # vocabulary - nested conditions, sources this product does not offer,
    # exclusions - and a parser would have to either understand all of it
    # or quietly drop what it did not. Kept whole, it is evidence; parsed
    # optimistically, it would be a lie about somebody's audience.
    rule_raw: dict[str, Any] = Field(default_factory=dict)
    # The provider's own description of what this was built to resemble,
    # whole and unread, for the audiences that were.
    #
    # Kept raw for the reason ``rule_raw`` above is, plus one of its own:
    # **the shape is not documented.** Meta publishes the fields that go
    # *in* and says of what comes back only that it is generated for this
    # subtype. Carrying the answer whole is how a shape nobody has written
    # down becomes something that can be read later without a guess having
    # been made in the meantime.
    #
    # It does not name the seed. No provider seen so far will say which
    # audience a lookalike was built from - the seed lists its children and
    # the child cannot name its parent - so an audience somebody built in
    # the provider's own console arrives here with its breadth and its
    # country and no origin at all.
    lookalike_raw: dict[str, Any] = Field(default_factory=dict)
    # How long the provider keeps somebody in it. Zero for a customer list,
    # which has no window - the people in one stay until they are removed.
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
    # How far back the provider looks, and how long somebody stays in once
    # they match. Days rather than the seconds some providers want, because
    # a person choosing this is choosing "the last month" - and an integer
    # count of seconds in a domain object is a unit conversion waiting to
    # be done twice.
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
    # ISO 3166-1 alpha-2, upper case. The one field here a provider does
    # not rename: both platforms seen so far take the same two letters.
    country: str


# What a hashed identifier looks like once it has been hashed: SHA-256, hex,
# lower case. Sixty-four characters, and the only shape allowed to cross
# this boundary.
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
    # ISO-3166 alpha-2, lower-cased before hashing. Hashed like everything
    # else here although it identifies nobody on its own: providers expect
    # the whole row in one form, and an unhashed value among hashed ones is
    # rejected rather than matched.
    country: str = ""

    @field_validator("*")
    @classmethod
    def _is_a_digest(cls, value: str) -> str:
        """Refuse anything that is not already hashed.

        The one guard in this package that exists for a reason other than
        correctness. A caller that forgot to hash gets an error here, at
        the boundary, rather than a hundred-per-cent match failure weeks
        later - or, far worse, a plaintext phone number in somebody else's
        logs.
        """
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
    # The provider's own handle for a multi-request upload, kept so a
    # continuation can name the session it belongs to and so a support
    # conversation has something to quote.
    session_id: str = ""
    # A few of the refused rows with the provider's reason, never the rows
    # themselves - what came back is hashed, and it stays that way here.
    invalid_samples: dict[str, str] = Field(default_factory=dict)
    # True by default, like every other write in this package.
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
    # When the *judgement* was made, not when the lead arrived. The
    # provider timestamps its own half; this is the half it does not have.
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
        """Money on a stage that has not produced any is refused here.

        At construction rather than in the adapter, because this is the
        boundary the mistake would cross silently: a provider accepts an
        amount on any event it is offered one with, and the result is an
        optimiser told that every answered telephone was worth nought.
        """
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
    # The provider's own handle for this request, kept for the reason the
    # upload keeps its session id: a support conversation about a figure
    # that does not match needs something to quote.
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class ActionResult:
    """The outcome of one write.

    ``dropped`` is not optional bookkeeping. Meta accepts a targeting spec
    and silently removes parts of it - some placements, some interests - and
    answers 200. Comparing what was sent against what came back is the only
    way to know, and the difference lands here so the audit log can keep it.
    """

    ok: bool
    ref: ExternalRef
    applied: dict[str, Any] = field(default_factory=dict)
    dropped: dict[str, Any] = field(default_factory=dict)
    # True by default everywhere it is constructed. Writing to a live ad
    # account is opt-in, never the path of least resistance.
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

    # What the caller stores, encrypted. Not always what a call is made
    # with - see ``ConnectPort.access_token``. Out of every repr: a grant
    # ends up in a log line sooner or later.
    token: str = Field(repr=False)
    expires_in: int = 0
    # What the provider actually granted, which a person can make narrower
    # than what was asked for by unticking a box on the consent screen.
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
    # People who saw the ad at least once in the range.
    reach: int = 0
    # The provider's estimate of how many of them would remember it.
    recallers: int = 0
