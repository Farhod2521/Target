"""Meta, expressed as the ports the rest of the system talks to.

This module is the translation layer, and it is the only place in the
project allowed to hold both vocabularies at once. Meta's words go in -
``OUTCOME_LEADS``, ``CAMPAIGN_PAUSED``, ``learning_stage_info`` - and
domain objects come out. Everything above it deals in ``adskit`` types and
would keep working against a provider that has never heard of Meta.

Two translations happen here and neither is optional:

* **Errors.** ``MetaAuthError`` becomes ``AuthFailed``. A service that
  catches ``code == 190`` is a service that breaks the day Google is added.
* **Delivery.** Meta has a dozen effective statuses and half of them
  describe the parent. A template branching on ``ADSET_PAUSED`` has
  hard-coded a provider into a screen.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from adskit.dto import (
    AccountStateDTO,
    ActionResult,
    AdDTO,
    AdPreviewDTO,
    AdSetDTO,
    AudienceDTO,
    AudienceMemberDTO,
    AudienceRuleDTO,
    AudienceStateDTO,
    CampaignDTO,
    ConversionReceiptDTO,
    CreativeDTO,
    FormEndingKind,
    GrantDTO,
    InterestDTO,
    IssueDTO,
    LeadDTO,
    LeadEventDTO,
    LeadFormDTO,
    LocationDTO,
    LookalikeSpecDTO,
    MemberUploadDTO,
    MetricsDTO,
    ObjectsDTO,
    PeopleCountDTO,
    ReachDTO,
    RecommendationDTO,
    RetiredOptionDTO,
    ReviewFeedbackDTO,
    RuleSupportDTO,
    SegmentMetricsDTO,
    StatusDTO,
)
from adskit.errors import (
    AccountActionRequired,
    AuthFailed,
    BidStrategyRefused,
    BudgetTooLow,
    InvalidRequest,
    LeadFormPrivacyMissing,
    LocationNotRecognized,
    LocationsOverlap,
    MediaTooLarge,
    NotFound,
    PaymentMethodMissing,
    PermissionDenied,
    ProviderError,
    RateLimited,
    ResultTruncated,
    TargetingOptionRetired,
    TemporaryFailure,
    TermsNotAccepted,
)
from adskit.refs import (
    BreakdownKind,
    Delivery,
    ExternalRef,
    GeoKind,
    Level,
    MinorUnits,
    Ranking,
    TraitKind,
)
from adskit.registry import ProviderBundle

from metaads import PROVIDER
from metaads.account_state import read_account_state
from metaads.audience_diff import same_audience
from metaads.audience_rules import event_of as meta_event
from metaads.audience_rules import excluded_event_of as meta_excluded_event
from metaads.audience_rules import supported_rules as meta_rule_support
from metaads.audiences import create_audience as write_audience
from metaads.audiences import (
    create_lookalike_audience as write_lookalike_audience,
)
from metaads.audiences import create_rule_audience as write_rule_audience
from metaads.audiences import delete_audience as remove_audience
from metaads.audiences import get_audience as read_audience
from metaads.audiences import list_audiences as read_audiences
from metaads.breakdowns import fetch_breakdown as read_breakdown
from metaads.campaigns import (
    BASE_STATUS_FIELDS,
    STATUS_FIELDS,
    count_campaign_adsets,
    get_object,
    list_ads,
    list_adsets,
    list_campaigns,
)
from metaads.client import GraphClient
from metaads.conversions import REPORT_WINDOW_DAYS
from metaads.conversions import report_leads as send_lead_events
from metaads.customer_lists import add_members as upload_members
from metaads.customer_lists import remove_members as withdraw_members
from metaads.discovery import (
    TRAIT_CLASSES,
    browse_traits,
    search_interests,
    search_locations,
    validate_interests,
)
from metaads.discovery import estimate_reach as fetch_estimate
from metaads.dto import (
    AdRow,
    AdSetRow,
    CampaignRow,
    CreativeRow,
    CustomAudienceRow,
    IssueRow,
    LeadFormRow,
    LeadRow,
    MemberUploadRow,
    RecommendationRow,
    ReviewFeedbackRow,
)
from metaads.errors import (
    MetaAPIError,
    MetaAuthError,
    MetaError,
    MetaPayloadTooLarge,
    MetaTemporaryError,
    PagesExhausted,
    RateLimitApproaching,
    refusal_key,
    retired_pairs,
)
from metaads.insights import (
    COMMENT_ACTIONS,
    LANDING_PAGE_ACTIONS,
    REACTION_ACTIONS,
    RESULTS_FIELD,
    SAVE_ACTIONS,
    SHARE_ACTIONS,
    VIDEO_VIEW_ACTIONS,
    action_count,
    action_value,
    differing_attribution,
    fetch_insights,
    fetch_people_counts,
    lead_actions_for,
    lead_count,
    meta_result_count,
    profile_visit_count,
    result_count,
    single_value,
)
from metaads.leadforms import list_forms as read_forms
from metaads.leads import LEADGEN_FIELD, subscribe_page
from metaads.leads import fetch_lead as read_lead
from metaads.leads import list_leads as read_leads
from metaads.lookalikes import ratio_of as meta_ratio
from metaads.money import META_MONEY
from metaads.oauth import authorize_url as oauth_dialog_url
from metaads.oauth import exchange_code, exchange_for_long_lived, inspect_token
from metaads.objects import read_ads, read_adsets, read_campaigns
from metaads.previews import get_preview as read_preview
from metaads.specs import (
    STATUS_ACTIVE,
    STATUS_PAUSED,
    THANK_YOU_CALL,
    THANK_YOU_NONE,
    THANK_YOU_WEBSITE,
)
from metaads.text import plain_text
from metaads.writes import delete_object as remove_object
from metaads.writes import read_targeting as read_adset_targeting
from metaads.writes import set_budget as write_budget
from metaads.writes import set_end_time as write_end_time
from metaads.writes import set_spend_cap as write_spend_cap
from metaads.writes import set_status as write_status
from metaads.writes import write_targeting

# Meta's effective statuses, read as what a person would want to know.
#
# **The two "somebody above paused it" values keep their own word.** An ad
# set reading CAMPAIGN_PAUSED is not paused itself: its switch is on, and
# telling its owner to switch it on sends them to a control that is already
# in the position they would move it to. Mapping both onto "paused" is
# what makes that happen: a screen then has to rebuild the distinction by
# walking to the parent row, which answers a near-enough question rather
# than this one, and every other reader of the column has no way to ask.
_DELIVERY: dict[str, Delivery] = {
    "ACTIVE": "active",
    "PAUSED": "paused",
    "CAMPAIGN_PAUSED": "paused_above",
    "ADSET_PAUSED": "paused_above",
    "PENDING_REVIEW": "pending",
    "PREAPPROVED": "pending",
    # Not a review: Meta is still applying a change. ``delivery_of`` answers
    # with the object's own switch; this line is for a read that has none.
    "IN_PROCESS": "pending",
    # Held until the account is paid for - its own word, because the fix
    # is a card and not a wait.
    "PENDING_BILLING_INFO": "billing",
    # Refused, or running with a policy problem. Both need the advertiser
    # to do something, which is the distinction the domain cares about.
    "DISAPPROVED": "rejected",
    "WITH_ISSUES": "rejected",
    "ADSET_ISSUE": "rejected",
    # Ran and stopped on its own: reached its end date, spent its budget,
    # or was put away. Not a problem, and not something to offer a
    # "resume" button for.
    "COMPLETED": "finished",
    "ARCHIVED": "finished",
    "DELETED": "finished",
}

_IN_PROCESS = "IN_PROCESS"

# Meta's error codes for "you may not do that", as opposed to "your token is
# no good". The difference decides whether the customer reconnects or the
# app needs a permission it was never granted.
_PERMISSION_CODES = frozenset({200, 294})

# 803 is "object does not exist or you cannot see it", which for our
# purposes is the same thing. 100 is not here: it is "Invalid parameter",
# which is a refused value - a malformed spec, a place nobody recognises -
# and never a missing object.
_NOT_FOUND_CODES = frozenset({803})

# Lead form terms of service, unaccepted. A *subcode*, because the code
# beside it is 100 - "Invalid parameter" - which is also what a malformed
# targeting spec and a retired placement come back as. The subcode is the
# only part that tells them apart, and the only part that reads the same
# whatever language Meta answers the account in.
#
# Checked before the code, for that reason.
_TERMS_SUBCODES = frozenset({1815089})

# The account is held pending a security check its owner has to clear in
# Meta's own console. A subcode again, and again because the code beside it
# is generic: 31 is "this request requires the user to take a pending
# action", which is a family rather than a reason.
#
# Meta answers this one with **HTTP 200** and an error object in the body,
# which is why the client checks the body as well as the status. Both
# halves are needed: without the body check nothing raises at all, and
# without this line it raises as a bad payload.
_ACTION_SUBCODES = frozenset({3858385})

# The daily budget is under this account's floor for this optimisation
# goal. A subcode once more, and the reason is the same one three times
# over: the code beside it is 100, which the adapter would otherwise turn
# into "the provider rejected the payload" and the screen into "change your
# text or your picture". The advertiser can fix this one themselves in
# about ten seconds, and only if somebody tells them what it is.
_BUDGET_SUBCODES = frozenset({1885272})

# "No Payment Method": the ad account has nothing Meta can charge. Code 100
# beside it, so as a rejected payload the screen would send the advertiser
# to their text; the fix is Meta's billing page. Seen in production on the
# ad, after the campaign and the ad set were already made.
_PAYMENT_SUBCODES = frozenset({1359188})

# A bid strategy the goal does not take: a cost cap on a goal Meta buys only
# with its automatic bidding. 1885204 is "Optimization goal only supports
# autobid" (seen for QUALITY_CALL), 2446166 "Optimization Goal Incompatible
# with Cost Cap" (seen for CONVERSATIONS). Code 100 beside both, so as a
# rejected payload the screen would send the advertiser to their text.
_BID_SUBCODES = frozenset({1885204, 2446166})

# "Location not recognized": the ad set names a place Meta cannot put on a
# map - a pin in open sea, a key its catalogue does not have. The code
# beside it is 100 again, and as a rejected payload the screen would send
# the advertiser to rewrite their ad; the fix is the geography.
_LOCATION_SUBCODES = frozenset({1487851})

# "Some locations conflict with each other": two places in the spec cover
# the same ground - a city beside the region it lies in. Code 100 again, and
# a different fix from the one above: nothing is misspelt, one of the two
# has to go.
_OVERLAP_SUBCODES = frozenset({1487756})

# "This Promotion Requires a Privacy Policy": the lead form on the ad links
# to none. Code 100 once more, and the fix is another form rather than
# another text or picture.
_PRIVACY_SUBCODES = frozenset({1892142})

# Meta's learning stages. Only the first means "delivery is still being
# bought and editing throws it away"; ``LEARNING_LIMITED`` means the ad set
# gave up on learning and is exactly the one an operator should be allowed
# to change. An absent stage means Meta has not said - normal for an ad set
# that never delivered - and is not treated as learning.
_LEARNING = "LEARNING"

# What Meta calls each verdict, lowercased, mapped onto the domain's own
# spelling. A closed map and not a ``.lower()``: an unrecognised value has
# to become "unknown" rather than travel into a column typed as a fixed
# set, and Meta has added a step to this scale before.
_RANKINGS: dict[str, Ranking] = {
    "above_average": "above_average",
    "average": "average",
    "below_average_10": "below_average_10",
    "below_average_20": "below_average_20",
    "below_average_35": "below_average_35",
    "unknown": "unknown",
}


def _ranking(value: object) -> Ranking:
    """One verdict as the domain spells it.

    Empty when Meta sent nothing, which is what every campaign and ad set
    row carries - the fields are asked for at ad level only. ``"unknown"``
    when Meta sent that word, meaning it has not seen enough impressions to
    judge yet: a real answer about a new ad, not a failure.

    Anything unrecognised also becomes ``"unknown"``. A verdict this
    package has never heard of is a verdict it cannot act on, and refusing
    the whole row over it would lose a day of spend to a new enum value.
    """
    if value is None:
        return ""
    return _RANKINGS.get(str(value).strip().lower(), "unknown")


def _issues(rows: tuple[IssueRow, ...]) -> tuple[IssueDTO, ...]:
    """Meta's ``issues_info`` in domain words.

    The code becomes a string here. Meta numbers them and the domain says
    codes are strings, because nothing promises the next provider uses
    digits - and because a code that is sometimes 0 and sometimes absent
    reads better as an empty string than as a zero that looks like a code.
    """
    return tuple(
        IssueDTO(
            code=str(row.error_code) if row.error_code else "",
            summary=plain_text(row.error_summary),
            message=plain_text(row.error_message),
            level=row.level,
            kind=row.error_type,
        )
        for row in rows
    )


def _recommendations(
    rows: tuple[RecommendationRow, ...],
) -> tuple[RecommendationDTO, ...]:
    """Meta's ``recommendations`` in domain words."""
    return tuple(
        RecommendationDTO(
            code=str(row.code) if row.code else "",
            title=plain_text(row.title),
            message=plain_text(row.message),
            importance=row.importance,
            confidence=row.confidence,
            blame_field=row.blame_field,
        )
        for row in rows
    )


def _review_feedback(row: ReviewFeedbackRow | None) -> ReviewFeedbackDTO | None:
    """Why an ad was refused, or ``None`` because it was not.

    ``None`` is passed through rather than turned into an empty DTO: an ad
    that was approved and an ad that was refused with nothing said are
    different, and the second is worth noticing.
    """
    if row is None:
        return None
    return ReviewFeedbackDTO(overall=row.overall, by_placement=row.placement_specific)


# How many names may be looked up one at a time after the bulk check left
# them unidentified. A ceiling rather than a limit anybody should reach:
# the bulk endpoint answers for most lists, and a run that needs more than
# this is a signal about the names rather than a reason to spend the
# account's call budget.
MAX_SEARCH_FALLBACK = 8

# The geography kinds this product targets, mapped to themselves so the
# narrowing below keeps its type. Meta's ``adgeolocation`` answers a dozen
# more - zip, neighborhood, geo_market, electoral_district - and every one
# of them that is not in here becomes "other" rather than being filed under
# whichever of the three it happens to resemble.
_GEO_KINDS: dict[str, GeoKind] = {
    "city": "city",
    "region": "region",
    "country": "country",
}

# The two delivery words an advertiser can actually ask for, and Meta's
# spelling of each. A map rather than ``.upper()``: the domain's vocabulary
# and Meta's agree on these two by coincidence, and the next provider's
# will not - Google calls the same pair ENABLED and PAUSED.
#
# The other four ``Delivery`` values are absent because they are not
# requests. "pending" and "rejected" are things a provider decided, and
# offering them here would let a caller ask for a state nobody can set.
_SETTABLE: dict[str, str] = {"active": STATUS_ACTIVE, "paused": STATUS_PAUSED}


def delivery_of(effective_status: str, status: str = "") -> Delivery:
    """Meta's effective status in domain words.

    Unknown values return ``unknown`` rather than guessing. Meta adds
    statuses between versions, and a wrong guess here is a screen telling
    somebody their ads are fine when they are not.

    ``IN_PROCESS`` says only that a change is still being applied, for a
    moment, so the object's own switch answers: Ads Manager shows such an ad
    as Active, and calling it under review sends its owner to wait for nothing.
    """
    word = effective_status.upper()
    if word == _IN_PROCESS and status:
        word = status.upper()
    return _DELIVERY.get(word, "unknown")


def translate_error(exc: MetaError) -> ProviderError:
    """One Meta failure as the domain's own.

    The class carries the decision. ``retryable`` is what a Celery task
    reads, and it must not require knowing a single Meta code.

    Meta's two advertiser-facing sentences travel with every one of them.
    They are the only part of a refusal written for the person who owns the
    account, and a screen that cannot reach them can only ever say "the
    provider said no" - which is what sends an owner to rewrite an ad three
    times over a security check Meta has already described in plain words.
    """
    translated = _translated(exc)
    translated.key = refusal_key(exc)
    return translated


def _translated(exc: MetaError) -> ProviderError:
    words = _user_words(exc)
    # First, because it is the one failure Meta did not report. Every
    # request succeeded and the answer was simply deeper than the read was
    # allowed to go, so none of the code-based branches below could ever
    # recognise it - it would fall through to ``InvalidRequest`` and read
    # as a bug in the request we sent.
    if isinstance(exc, PagesExhausted):
        return ResultTruncated(str(exc), rows_read=len(exc.rows), pages=exc.pages)
    if isinstance(exc, RateLimitApproaching):
        return RateLimited(
            str(exc),
            code=str(exc.code or ""),
            retry_after_seconds=exc.retry_after or 0,
        )
    if isinstance(exc, MetaTemporaryError):
        return TemporaryFailure(str(exc), code=str(exc.code or ""), **words)
    if isinstance(exc, MetaAuthError):
        # Before the code, like the terms check below it: the subcode is
        # what separates "reconnect the account" from "go and confirm it
        # is you", and those are different sentences to a person.
        if exc.subcode in _ACTION_SUBCODES:
            return AccountActionRequired(str(exc), code=str(exc.subcode or ""), **words)
        if exc.code in _PERMISSION_CODES:
            return PermissionDenied(str(exc), code=str(exc.code or ""), **words)
        return AuthFailed(str(exc), code=str(exc.code or ""), **words)
    if isinstance(exc, MetaPayloadTooLarge):
        return MediaTooLarge(str(exc), code="413")
    if isinstance(exc, MetaAPIError):
        # First of the refusals, because it is the only one recognised by
        # what it carries rather than by a number: if the mapping can be
        # read, this is that failure and nothing else can be.
        retired = _retired(exc)
        if retired:
            return TargetingOptionRetired(
                str(exc),
                retired=retired,
                code=str(exc.subcode or exc.code or ""),
                **words,
            )
        if exc.subcode in _TERMS_SUBCODES:
            return TermsNotAccepted(str(exc), code=str(exc.subcode or ""), **words)
        if exc.subcode in _BUDGET_SUBCODES:
            return BudgetTooLow(str(exc), code=str(exc.subcode or ""), **words)
        if exc.subcode in _PAYMENT_SUBCODES:
            return PaymentMethodMissing(str(exc), code=str(exc.subcode or ""), **words)
        if exc.subcode in _BID_SUBCODES:
            return BidStrategyRefused(str(exc), code=str(exc.subcode or ""), **words)
        if exc.subcode in _LOCATION_SUBCODES:
            return LocationNotRecognized(str(exc), code=str(exc.subcode or ""), **words)
        if exc.subcode in _OVERLAP_SUBCODES:
            return LocationsOverlap(str(exc), code=str(exc.subcode or ""), **words)
        if exc.subcode in _PRIVACY_SUBCODES:
            return LeadFormPrivacyMissing(
                str(exc), code=str(exc.subcode or ""), **words
            )
        if exc.code in _NOT_FOUND_CODES:
            return NotFound(str(exc), code=str(exc.code or ""), **words)
        return InvalidRequest(str(exc), code=str(exc.code or ""), **words)
    return InvalidRequest(str(exc))


def _retired(exc: MetaAPIError) -> tuple[RetiredOptionDTO, ...]:
    """The catalogue entries this refusal says have been withdrawn.

    Read from ``error_user_msg`` - the sentence Meta writes for the
    advertiser - because that is where the array is. The developer string
    beside it names the parameter and not the values.
    """
    return tuple(
        RetiredOptionDTO(**pair) for pair in retired_pairs(exc.user_message or "")
    )


def _user_words(exc: MetaError) -> dict[str, str]:
    """Meta's advertiser-facing pair, or nothing when it sent none.

    Most refusals carry only the developer string. Empty is the normal
    case and the screen is written for it.
    """
    return {
        "user_title": getattr(exc, "user_title", ""),
        "user_message": getattr(exc, "user_message", ""),
    }


@contextmanager
def session(token: str) -> Iterator[GraphClient]:
    """One connection for one call, and Meta's failures as the domain's.

    Both jobs in one place because they have the same scope. Translating
    per call site would mean a service eventually catching a ``MetaError``
    that slipped through - and that service would then be the second place
    in the codebase that knows Meta's error codes.

    Public because :mod:`metaads.launcher` needs the same guarantee. It is
    not a port, but it is above the boundary, and a second copy of the
    error translation is exactly what this module's docstring warns about.
    """
    graph = GraphClient(token=token)
    try:
        yield graph
    except MetaError as exc:
        raise translate_error(exc) from exc
    finally:
        graph.close()


class MetaCampaigns:
    """The read half of :class:`adskit.CampaignControlPort`.

    Stateless, as every port implementation is: the token arrives per call
    and nothing is cached between them. One ``GraphClient`` is opened per
    call and closed again, so a worker that dies mid-sync leaks nothing.

    Writes - pause, resume, budget - are here, and every one of them
    defaults to ``dry_run=True``. What is *not* here is the decision to
    make one: an ad set mid-learning, an object already in the state being
    asked for, a button pressed twice. Each needs a clock, a database and
    an audit trail, and a stateless translator has none of the three.
    """

    def list_campaigns(self, *, account: ExternalRef, token: str) -> list[CampaignDTO]:
        with session(token) as graph:
            rows = list_campaigns(account_id=account.id, token=token, client=graph)
        return [self._campaign(row) for row in rows]

    def list_adsets(self, *, account: ExternalRef, token: str) -> list[AdSetDTO]:
        with session(token) as graph:
            rows = list_adsets(account_id=account.id, token=token, client=graph)
        return [self._adset(row) for row in rows]

    def list_ads(self, *, account: ExternalRef, token: str) -> list[AdDTO]:
        with session(token) as graph:
            rows = list_ads(account_id=account.id, token=token, client=graph)
        return [self._ad(row) for row in rows]

    def read_objects(
        self, *, account: ExternalRef, refs: Sequence[ExternalRef], token: str
    ) -> ObjectsDTO:
        """Read by id, so nothing else in the account can fail the read.

        ``account`` is not needed: Meta answers an object by its id alone,
        for any token that can see it.
        """
        wanted: dict[Level, list[str]] = {"campaign": [], "adset": [], "ad": []}
        for ref in refs:
            if ref.level in wanted:
                wanted[ref.level].append(ref.id)
        with session(token) as graph:
            campaigns = read_campaigns(
                ids=wanted["campaign"], token=token, client=graph
            )
            adsets = read_adsets(ids=wanted["adset"], token=token, client=graph)
            ads = read_ads(ids=wanted["ad"], token=token, client=graph)
        return ObjectsDTO(
            campaigns=tuple(self._campaign(row) for row in campaigns),
            adsets=tuple(self._adset(row) for row in adsets),
            ads=tuple(self._ad(row) for row in ads),
        )

    def count_adsets(self, *, campaign: ExternalRef, token: str) -> int:
        with session(token) as graph:
            return count_campaign_adsets(
                campaign_id=campaign.id, token=token, client=graph
            )

    def read_account(self, *, account: ExternalRef, token: str) -> AccountStateDTO:
        """Whether the account can pay for its advertising right now.

        See :mod:`metaads.account_state`.
        """
        with session(token) as graph:
            return read_account_state(account=account, token=token, client=graph)

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        """What state one object is in right now, read fresh.

        The fields asked for depend on the level, not on the provider: only
        ad sets have a learning stage, only campaigns and ad sets hold a
        budget, and asking a node for a field it does not have is an error
        rather than an empty answer.

        A level nobody listed falls back to the two fields every object in
        the hierarchy has. Wrong in the direction that still works: the read
        succeeds and answers less, where a guessed extra field would fail
        every call at that level - and this is the read taken immediately
        before a write.
        """
        fields = STATUS_FIELDS.get(ref.level, BASE_STATUS_FIELDS)

        with session(token) as graph:
            payload = get_object(
                object_id=ref.id, fields=fields, token=token, client=graph
            )

        stage = payload.get("learning_stage_info") or {}
        learning = stage.get("status", "") if isinstance(stage, dict) else ""
        effective = payload.get("effective_status", "")
        budget = payload.get("daily_budget")

        return StatusDTO(
            ref=ref,
            status=payload.get("status", ""),
            effective_status=effective,
            delivery=delivery_of(effective, payload.get("status", "")),
            learning_status=learning,
            is_learning=learning.upper() == _LEARNING,
            # Absent, not zero, on an object whose budget lives one level
            # down. Meta sends the figure as a string of minor units.
            daily_budget_minor=MinorUnits(int(budget)) if budget is not None else None,
        )

    def get_preview(
        self, *, ref: ExternalRef, ad_format: str, token: str
    ) -> AdPreviewDTO:
        """Where this ad can be seen as its audience will see it.

        The whole of the work is in :mod:`metaads.previews`, including the
        two things Meta does not document: the address arrives HTML-escaped
        and it is signed with no published lifetime. What this method adds
        is the boundary - Meta's frame becomes a DTO, and Meta's failures
        become the domain's.

        ``ref`` is passed through untouched. The edge is the same on an ad
        and on the creative under it, so which one the caller holds is not
        a decision this has to make.

        **The address is checked against Meta's own preview host before it
        gets here**, in the package, because that is the layer that knows
        what the legitimate host is. Everything above renders this into an
        ``iframe``, and a check made anywhere else would be a check made
        without that knowledge.
        """
        with session(token) as graph:
            frame = read_preview(
                object_id=ref.id, ad_format=ad_format, token=token, client=graph
            )

        return AdPreviewDTO(
            ref=ref,
            ad_format=ad_format,
            src=frame.src,
            width=frame.width,
            height=frame.height,
        )

    def set_status(
        self, *, ref: ExternalRef, status: str, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Stop or start one object, at whatever level it sits.

        Meta answers a bare ``{"success": true}`` and does not report the
        new state, so nothing is read back here. What the object looks like
        afterwards is the next sync's answer, and asking for it now would
        cost a call to learn what was just sent.

        The decision of *whether* to call this is not here. Whether an ad
        set is mid-learning, whether it was already paused, whether
        somebody clicked twice - all of that needs a clock, a database and
        an audit trail, none of which a stateless translator has.
        """
        meta_status = _SETTABLE.get(status.strip().lower())
        if meta_status is None:
            # Ours, not Meta's: the call never leaves. Raised rather than
            # ignored because a status nobody can set is a caller bug, and
            # a silent no-op would report success for a button that did
            # nothing.
            raise InvalidRequest(f"{PROVIDER} cannot be asked for status {status!r}")

        with session(token) as graph:
            ok = write_status(
                object_id=ref.id,
                status=meta_status,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return ActionResult(
            ok=ok,
            ref=ref,
            # The domain's word, not the one that went out. An audit row is
            # read by whoever asks what happened, and ``PAUSED`` there would
            # be Meta's vocabulary stored in our own table.
            applied={"status": status.strip().lower()},
            dry_run=dry_run,
        )

    def set_budget(
        self,
        *,
        ref: ExternalRef,
        daily_budget_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Replace the daily budget on the object that holds it.

        Meta enforces a floor and refuses below it with ``100/1885272``,
        which :func:`translate_error` turns into ``BudgetTooLow`` - the one
        refusal in this family the advertiser clears themselves. No floor is
        checked here: it differs per account and per optimisation goal, the
        caller has both, and a second copy of that arithmetic in the
        adapter is a second copy to keep in step.
        """
        with session(token) as graph:
            ok = write_budget(
                object_id=ref.id,
                daily_budget_minor=int(daily_budget_minor),
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return ActionResult(
            ok=ok,
            ref=ref,
            applied={"daily_budget_minor": int(daily_budget_minor)},
            dry_run=dry_run,
        )

    def set_end_time(
        self, *, ref: ExternalRef, end_time: str, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Say when this ad set stops.

        ``end_time`` arrives as ISO-8601 text with an offset, and it stays
        text all the way to the wire. A datetime crossing this boundary
        would need a timezone to be rendered in, this package has none, and
        guessing one is how a campaign ends at nine in the evening in a
        country nobody asked about.

        Meta refuses an end time in the past and one less than a day out on
        a daily-budget ad set; both come back as ordinary Graph errors and
        are translated where every other refusal is.
        """
        with session(token) as graph:
            ok = write_end_time(
                object_id=ref.id,
                end_time=end_time,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return ActionResult(
            ok=ok, ref=ref, applied={"end_time": end_time}, dry_run=dry_run
        )

    def set_spend_cap(
        self,
        *,
        ref: ExternalRef,
        spend_cap_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The most this campaign may spend in total.

        No floor is checked here, for the reason :meth:`set_budget` gives
        about its own: Meta's minimum differs per currency, it publishes and
        changes it, and a second copy of that arithmetic in the adapter is a
        second copy to keep in step. A cap below what has already been spent
        is refused by Meta for the same reason it refuses a low budget, and
        arrives as the same kind of error.
        """
        with session(token) as graph:
            ok = write_spend_cap(
                object_id=ref.id,
                spend_cap_minor=int(spend_cap_minor),
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return ActionResult(
            ok=ok,
            ref=ref,
            applied={"spend_cap_minor": int(spend_cap_minor)},
            dry_run=dry_run,
        )

    def delete(
        self, *, ref: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Delete one object - and, for a campaign, everything inside it.

        Meta's ``DELETE`` on a campaign takes its ad sets and ads with it,
        and none of the three can be brought back. That is why "are you
        sure" is asked above this package and never here: a stateless
        translator has nobody to ask.

        A rehearsal and a dry-run id answer true without a call, exactly as
        they do for the rollback that shares
        :func:`metaads.writes.delete_object`.
        """
        with session(token) as graph:
            ok = remove_object(
                object_id=ref.id, token=token, client=graph, dry_run=dry_run
            )

        # The domain's word for what was asked, like ``set_status`` above.
        return ActionResult(
            ok=ok, ref=ref, applied={"status": "deleted"}, dry_run=dry_run
        )

    # --- Translation -----------------------------------------------------
    @staticmethod
    def _ref(level: Level, external_id: str) -> ExternalRef:
        return ExternalRef(provider=PROVIDER, level=level, id=external_id)

    @classmethod
    def _campaign(cls, row: CampaignRow) -> CampaignDTO:
        budget = row.daily_budget_minor
        cap = row.spend_cap_minor
        return CampaignDTO(
            ref=cls._ref("campaign", row.id),
            name=row.name,
            status=row.status,
            effective_status=row.effective_status,
            delivery=delivery_of(row.effective_status, row.status),
            objective_raw=row.objective,
            daily_budget_minor=MinorUnits(budget) if budget is not None else None,
            spend_cap_minor=MinorUnits(cap) if cap is not None else None,
            # Meta reports currency on the ad account and nowhere below it.
            # Left empty rather than guessed: the caller has the account and
            # knows, and a DTO that invents a value is worse than one that
            # admits it was not told.
            currency="",
            special_ad_categories=row.special_ad_categories,
            created_time=row.created_time,
            issues=_issues(row.issues_info),
            recommendations=_recommendations(row.recommendations),
        )

    @classmethod
    def _adset(cls, row: AdSetRow) -> AdSetDTO:
        budget = row.daily_budget_minor
        return AdSetDTO(
            ref=cls._ref("adset", row.id),
            campaign_ref=cls._ref("campaign", row.campaign_id),
            name=row.name,
            status=row.status,
            effective_status=row.effective_status,
            delivery=delivery_of(row.effective_status, row.status),
            optimization_goal_raw=row.optimization_goal,
            billing_event_raw=row.billing_event,
            destination_type_raw=row.destination_type,
            daily_budget_minor=MinorUnits(budget) if budget is not None else None,
            currency="",
            targeting_raw=row.targeting,
            promoted_object_raw=row.promoted_object,
            learning_status=row.learning_status,
            is_learning=row.learning_status.upper() == _LEARNING,
            start_time=row.start_time,
            end_time=row.end_time,
            issues=_issues(row.issues_info),
            recommendations=_recommendations(row.recommendations),
        )

    @classmethod
    def _ad(cls, row: AdRow) -> AdDTO:
        return AdDTO(
            ref=cls._ref("ad", row.id),
            adset_ref=cls._ref("adset", row.adset_id),
            name=row.name,
            status=row.status,
            effective_status=row.effective_status,
            delivery=delivery_of(row.effective_status, row.status),
            creative_external_id=row.creative_external_id,
            creative=cls._creative(row.creative),
            lead_form_external_id=row.lead_form_external_id,
            issues=_issues(row.issues_info),
            review_feedback=_review_feedback(row.ad_review_feedback),
        )

    @classmethod
    def _creative(cls, row: CreativeRow) -> CreativeDTO | None:
        """The ad's content, or ``None`` when Meta sent none.

        An empty id is the only test worth making. Every other field on a
        creative is legitimately blank on some real creative - a post-based
        one has no words of its own, an image one has no video id - so
        checking any of them would throw away rows that are simply of a
        shape this account happens to use.

        The story spec is kept whole in ``story_raw`` **and** read into
        columns. Not a duplicate: the columns are what gets filtered and
        compared, and the block is what a rebuild starts from, since Meta
        does not let a creative be edited at all.
        """
        if not row.id:
            return None
        return CreativeDTO(
            ref=cls._ref("creative", row.id),
            name=row.name,
            status=row.status,
            kind=row.kind,
            message=row.message,
            headline=row.headline,
            description=row.description,
            link_url=row.link_url,
            call_to_action=row.call_to_action,
            image_hash=row.image_hash,
            video_id=row.video_id,
            # Meta's own rendering of the creative when it sent one, and
            # the still the advertiser supplied for a video when it did
            # not. Two fields with one job on screen, so one column.
            thumbnail_url=row.thumbnail_url or row.image_url,
            page_id=row.page_id,
            instagram_user_id=row.instagram_user_id,
            post_external_id=row.post_id,
            story_raw=row.object_story_spec,
        )


class MetaAudiences:
    """Who an ad set is shown to: found, measured, and replaced.

    Four methods and three different jobs. :meth:`find_interests` and
    :meth:`find_locations` turn words into things Meta will accept,
    :meth:`estimate_reach` says how many people that comes to, and
    :meth:`apply` writes it.

    The two lookups answer differently on purpose. An interest is confirmed
    on the owner's behalf in the background, so only an exact match counts;
    a place is picked from a list by a person, so the whole list comes
    back. The rule underneath both: never target something nobody chose.
    """

    def find_interests(self, *, names: list[str], token: str) -> list[InterestDTO]:
        """Words in, targetable interests out. Two endpoints, one promise.

        ``adinterestvalid`` first, because it answers for the whole list in
        one call. What that endpoint cannot guarantee is an **id**, and an
        interest without one cannot be targeted - so anything it leaves
        unidentified is asked again through ``adinterest``, which is the
        endpoint whose job is returning ids.

        The second pass costs one call per unresolved name, which is why it
        is a fallback and why it is capped. It also accepts only an exact
        match: it exists to find the same interest under a different
        capitalisation, never to quietly target something else because the
        owner's word was close to it.
        """
        if not names:
            # Meta answers an empty interest_list with an error, and asking
            # it whether it recognises nothing is not a question worth a
            # round trip.
            return []

        with session(token) as graph:
            rows = validate_interests(names=names, token=token, client=graph)
            found = [self._interest(row) for row in rows if _recognised(row)]

            resolved = {_folded(item.name) for item in found}
            missing = [name for name in names if _folded(name) not in resolved]

            for name in missing[:MAX_SEARCH_FALLBACK]:
                match = _exact_match(
                    name, search_interests(query=name, token=token, client=graph)
                )
                if match is not None:
                    found.append(self._interest(match))

        return found

    def find_traits(
        self, *, kind: TraitKind, names: list[str], token: str
    ) -> list[InterestDTO]:
        """Names in, rows of one closed catalogue out.

        A browse and an exact match, which is the whole difference from
        :meth:`find_interests` above. Meta publishes each of these classes
        as a fixed list and ignores a query string on the endpoint, so the
        list is fetched whole and matched here - one call for any number of
        names, however long the list.

        **The match is exact, folded, and never fuzzy.** These are targeting
        rows going into somebody's audience without a person confirming
        them, and a near match is not a spelling variant here the way it is
        for an interest - "Recently moved" and "Recently relocated" would be
        two different populations if Meta published both.

        An unknown class is refused rather than answered empty. Empty is a
        real answer from this endpoint - it is what a class unavailable in
        the advertiser's market returns - so a caller that misspelled a
        class would read a refusal as a market restriction and go on
        building a campaign with an audience it thinks it narrowed.
        """
        klass = TRAIT_CLASSES.get(kind)
        if klass is None:
            raise InvalidRequest(f"no such targeting class: {kind!r}")
        if not names:
            return []

        wanted = {_folded(name) for name in names}
        with session(token) as graph:
            rows = browse_traits(klass=klass, token=token, client=graph)

        return [
            self._interest(row, kind=kind)
            for row in rows
            if _folded(str(row.get("name", ""))) in wanted
        ]

    def find_locations(
        self, *, query: str, country_code: str, token: str, language: str = ""
    ) -> list[LocationDTO]:
        """One word in, the places Meta would accept it as, out.

        Ranked and returned whole, unlike :meth:`find_interests` above,
        which takes the exact match or nothing. The difference is what the
        two answers are for: an interest is confirmed on the owner's behalf
        in the background, so a near-match taken automatically would target
        something nobody chose - while a place is *picked from a list by a
        person*, and the list is useless if it only ever contains what was
        typed exactly. "Tashkent", "Toshkent" and "Toshkent Shahri" are one
        city, two spellings and a region, and only the owner knows which.

        ``country_code`` orders rather than filters. The advertiser's own
        country first, everything else after, nothing dropped: a shop near a
        border advertises across it, and a Tashkent in Kazakhstan is a real
        answer to somebody. Rows Meta returns without a country of their own
        keep their place rather than sinking - an unlabelled row is Meta
        being terse, not a place somewhere else.
        """
        if not query.strip():
            return []

        with session(token) as graph:
            rows = search_locations(
                query=query, token=token, language=language, client=graph
            )

        wanted = country_code.strip().upper()
        found = [self._location(row) for row in rows]
        if not wanted:
            return found

        return sorted(found, key=lambda place: place.country_code.upper() != wanted)

    def estimate_reach(
        self,
        *,
        account: ExternalRef,
        targeting: dict[str, object],
        optimization_goal: str,
        token: str,
    ) -> ReachDTO:
        """``delivery_estimate``, read as a range rather than a figure.

        Meta answers ``estimate_ready: false`` while it is still working,
        and answers zeroes at the same time. Passing those zeroes on as a
        reach of nobody would send an owner off to widen an audience that
        was never narrow, so the flag is carried and the caller waits.

        **A negative bound is a refusal, not a number.** Meta stopped
        estimating specs that name certain custom audiences - a customer
        file matched on more than one key among them - and says so by
        answering ``-1`` rather than by failing: *"The API returns a '-1'
        value as an audience size estimate."* This product uploads exactly
        such a file, so the case is ordinary rather than exotic, and a
        ``-1`` carried through as an integer becomes "about -1 people" on
        somebody's review screen.
        """
        with session(token) as graph:
            payload = fetch_estimate(
                account_id=account.id,
                targeting=dict(targeting),
                optimization_goal=optimization_goal,
                token=token,
                client=graph,
            )

        if not payload:
            return ReachDTO(ready=False)

        lower = _as_int(payload.get("estimate_mau_lower_bound"))
        upper = _as_int(payload.get("estimate_mau_upper_bound"))
        if lower < 0 or upper < 0:
            return ReachDTO(available=False)

        return ReachDTO(
            lower=lower,
            upper=upper,
            ready=bool(payload.get("estimate_ready", True)),
        )

    def apply(
        self,
        *,
        ref: ExternalRef,
        targeting: dict[str, object],
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Replace who this ad set is shown to.

        The spec goes out whole. Meta has no way to change one part of an
        audience - there is no "add an interest" call - so a caller wanting
        a wider radius sends the entire document back with that one figure
        edited, and anything it forgets to include is thereby removed.
        Building that document is the caller's job and deliberately not
        this method's: the ad set's current spec lives in the mirror, and
        an adapter that read it back to merge would be guessing which of
        the two versions the owner actually approved.

        ``dropped`` is where the honesty lives. Meta accepts a spec,
        removes the parts it no longer recognises, and answers success -
        so the result says both that the write landed and how much of it
        did.
        """
        with session(token) as graph:
            written = write_targeting(
                object_id=ref.id,
                targeting=targeting,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return ActionResult(
            ok=True,
            ref=ref,
            applied={"targeting": written.returned or dict(targeting)},
            dropped=written.dropped,
            dry_run=dry_run,
        )

    def read_targeting(self, *, ref: ExternalRef, token: str) -> dict[str, object]:
        """The ad set's audience as Meta holds it now."""
        with session(token) as graph:
            return read_adset_targeting(object_id=ref.id, token=token, client=graph)

    def same_targeting(
        self, first: dict[str, object], second: dict[str, object]
    ) -> bool:
        """See :mod:`metaads.audience_diff`."""
        return same_audience(first, second)

    @staticmethod
    def _interest(
        row: dict[str, object], *, kind: TraitKind = "interest"
    ) -> InterestDTO:
        """One catalogue row, read defensively.

        Meta replaced a single ``audience_size`` with a lower and an upper
        bound and still answers the old way on some accounts. Both spellings
        are read, so an account on the older shape shows a size instead of a
        confident zero.

        ``kind`` is the caller's, not the row's. Meta does answer a ``type``
        on a browsed category and it is not worth trusting for this: the
        value decides which key of a targeting spec the row goes into, and a
        row filed under a name we did not expect would end up in the wrong
        block - accepted by Meta, matched against nobody, delivered as a
        narrower audience than anybody chose.
        """
        legacy = _as_int(row.get("audience_size"))
        lower = _as_int(row.get("audience_size_lower_bound")) or legacy
        upper = _as_int(row.get("audience_size_upper_bound")) or legacy
        path = row.get("path")

        return InterestDTO(
            ref=ExternalRef(
                provider=PROVIDER, level="interest", id=str(row.get("id", ""))
            ),
            name=str(row.get("name", "")),
            kind=kind,
            audience_lower=lower,
            audience_upper=upper,
            path=tuple(str(part) for part in path) if isinstance(path, list) else (),
        )

    @staticmethod
    def _location(row: dict[str, object]) -> LocationDTO:
        """One geography row, in the domain's words.

        ``supports_radius`` is decided here and not on the screen, because
        deciding it needs Meta's rules: a radius may be drawn around a city
        and around a dropped pin, and around nothing else. Meta accepts
        ``regions`` and ``countries`` entries carrying a radius and then
        ignores it - the ad set is created, delivers to the whole region,
        and the number the owner typed appears nowhere.

        ``type`` is narrowed rather than trusted. Meta answers ``zip``,
        ``neighborhood``, ``geo_market`` and more on this endpoint, and a
        row of a kind this product does not model has to stay visibly
        unmodelled rather than be filed as a city.
        """
        kind = str(row.get("type", ""))
        region = str(row.get("region", ""))
        country = str(row.get("country_name", ""))

        return LocationDTO(
            ref=ExternalRef(
                provider=PROVIDER, level="location", id=str(row.get("key", ""))
            ),
            name=str(row.get("name", "")),
            kind=_GEO_KINDS.get(kind, "other"),
            country_code=str(row.get("country_code", "")),
            # A city is told apart by its region, a region by its country.
            # Both are how a person picks between two rows spelled the same.
            context=region or country,
            parent_id=str(row.get("region_id") or "") if kind == "city" else "",
            supports_radius=kind == "city",
        )


def _folded(value: str) -> str:
    """One name, compared the way two systems that both wrote it would.

    Case and surrounding space only. Anything looser would start matching
    interests that merely resemble each other, which is the whole thing
    the fallback above is careful not to do.
    """
    return " ".join(value.split()).casefold()


def _exact_match(name: str, rows: list[dict[str, object]]) -> dict[str, object] | None:
    """The search result that *is* this name, or nothing.

    Meta ranks its results by relevance, so the first row is always
    something - and taking it would mean an owner who asked for one
    audience getting another without being told. Better to report the name
    as unrecognised, which the screen already knows how to show.
    """
    wanted = _folded(name)
    for row in rows:
        if _folded(str(row.get("name", ""))) == wanted and _recognised(row):
            return row
    return None


def _recognised(row: dict[str, object]) -> bool:
    """Whether Meta claims this name at all.

    ``valid`` is what ``adinterestvalid`` answers with, and a row without an
    id is unusable whatever it says: targeting is built from ids, so a
    "valid" name Meta declined to identify would be dropped one layer later
    with less to say about why.
    """
    if row.get("valid") is False:
        return False
    return bool(str(row.get("id", "")).strip())


def _as_int(value: object) -> int:
    """Meta sends counts as numbers on one endpoint and strings on another."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


class MetaAudienceSources:
    """The audiences an advertiser owns, as :class:`adskit.AudienceSourcePort`.

    Stateless like every other port implementation here, and the only one
    whose calls can carry anything about a person. What reaches
    :meth:`add_members` is already hashed - the DTO refuses to hold
    anything else - so nothing in this class or below it has ever seen an
    email address.

    Meta's own two states are read here and turned into one answer the
    product can act on. ``operation_status`` says whether the last write
    has been processed and ``delivery_status`` whether the result can be
    advertised to, and an audience is routinely one and not the other: a
    finished upload that produced too few people is done and unusable at
    the same time. Both travel raw beside :attr:`AudienceDTO.is_ready` for
    the operator comparing against Meta's own screen.
    """

    def list_audiences(self, *, account: ExternalRef, token: str) -> list[AudienceDTO]:
        with session(token) as graph:
            rows = read_audiences(account_id=account.id, token=token, client=graph)
        return [self._audience(row) for row in rows]

    def get_audience(self, *, ref: ExternalRef, token: str) -> AudienceDTO:
        with session(token) as graph:
            row = read_audience(audience_id=ref.id, token=token, client=graph)
        return self._audience(row)

    def create_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Create the empty container.

        **The terms refusal is prevented rather than translated, and that
        is a decision worth reading.** Meta answers a failed creation with
        code 2654, which covers at least three different things - terms
        never accepted, no permission on the data source, a source too
        small - and mapping it to :class:`adskit.TermsNotAccepted` the way
        the lead form's subcode is mapped would tell an advertiser to sign
        an agreement when their real problem was something else. The
        lead-form case earns its line in ``_TERMS_SUBCODES`` because it has
        a *subcode* that means one thing; this one has no such thing that
        has been seen rather than guessed at.

        So it stays an :class:`adskit.InvalidRequest` carrying Meta's own
        advertiser-facing sentence, which does name the cause, and the
        product asks the question up front instead: the account read
        carries ``tos_accepted`` and the caller checks it before anybody
        uploads a spreadsheet. See
        ``AdAccountDTO.custom_audience_terms_accepted``.
        """
        with session(token) as graph:
            created = write_audience(
                account_id=account.id,
                name=name,
                description=description,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return ActionResult(
            ok=True,
            ref=self._ref(created),
            applied={"name": name, "description": description},
            dry_run=dry_run,
        )

    def supported_rules(self) -> list[RuleSupportDTO]:
        """Which rule audiences Meta builds. A table, not a call.

        **Video is absent.** Every platform builds an audience from who
        watched a video, Meta included - but the current guides list nine
        engagement source types and video is not among them, and the only
        JSON example anybody can find sits on documentation pages archived
        at v2.6. Writing it from those would be writing a decade-old shape
        against a v26.0 edge.

        Instagram is one step further off: ``ig_business`` *is*
        documented, but nothing in this product stores an Instagram
        account id to put in the rule.
        """
        return meta_rule_support()

    def create_rule_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        rule: AudienceRuleDTO,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Create an audience Meta fills from a rule.

        ``applied`` carries the rule in the domain's own words, plus the
        Meta words that are worth keeping: the event it gathers on and, for
        an action that subtracts, the event it takes back out. The audit row
        is read by people, and "lead_form + submitted, 30 kun" is the
        sentence somebody needs - while the two raw events beside it are
        what an operator compares against Ads Manager, the same split every
        status column in this package makes. The JSON envelope is not here:
        that is the document, not a word, and a table kept for years does
        not need Meta's grammar in it.

        ``excluded_event_raw`` is empty for every action that only gathers,
        and empty means "nobody is taken out" rather than "not known" -
        there is no third state for it to be confused with.
        """
        with session(token) as graph:
            created = write_rule_audience(
                account_id=account.id,
                name=name,
                description=description,
                rule=rule,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return ActionResult(
            ok=True,
            ref=self._ref(created),
            applied={
                "name": name,
                "description": description,
                "kind": rule.kind,
                "action": rule.action,
                "source": str(rule.source),
                "retention_days": rule.retention_days,
                "event_raw": meta_event(rule),
                "excluded_event_raw": meta_excluded_event(rule),
            },
            dry_run=dry_run,
        )

    def create_lookalike_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        spec: LookalikeSpecDTO,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Create an audience of people who resemble one that already exists.

        **The seed's contents never move.** Meta holds it; this hands over
        its id. Which is why the customer-list terms are not checked here
        even when the seed is a customer list - agreeing to hand over other
        people's details was done at the moment they were handed over, and
        asking again for an operation that sends nobody would be teaching
        somebody to sign things that do not apply.

        ``applied`` carries the choice in the domain's own words plus the
        one Meta word worth keeping: the ratio it was spelled as. The same
        split ``create_rule_audience`` makes above and every status column
        in this package makes - a person reading the audit row wants
        "balanced", and an operator comparing against Ads Manager wants
        "0.05".

        **The origin is in ``applied`` because it is the only place it will
        ever be.** Meta will not answer ``origin_audience_id`` on a read,
        so this row and whatever the caller writes down are the whole
        record of what this audience was built from.
        """
        with session(token) as graph:
            created = write_lookalike_audience(
                account_id=account.id,
                name=name,
                description=description,
                spec=spec,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return ActionResult(
            ok=True,
            ref=self._ref(created),
            applied={
                "name": name,
                "description": description,
                "origin": str(spec.origin),
                "breadth": spec.breadth,
                "country": spec.country,
                "ratio_raw": meta_ratio(spec),
            },
            dry_run=dry_run,
        )

    def add_members(
        self,
        *,
        ref: ExternalRef,
        members: Sequence[AudienceMemberDTO],
        token: str,
        dry_run: bool = True,
    ) -> MemberUploadDTO:
        """Post the customer list, in as many requests as Meta's cap needs."""
        with session(token) as graph:
            answer = upload_members(
                audience_id=ref.id,
                members=members,
                token=token,
                client=graph,
                dry_run=dry_run,
            )
        return self._upload(ref, answer, dry_run=dry_run)

    def remove_members(
        self,
        *,
        ref: ExternalRef,
        members: Sequence[AudienceMemberDTO],
        token: str,
        dry_run: bool = True,
    ) -> MemberUploadDTO:
        """Withdraw people from the audience, by the digests that added them.

        A real DELETE carrying the rows in its body, rather than the POST
        with ``?method=delete`` that Meta also accepts. The verb is the
        evidence: this is the call an erasure audit asks about, and a
        removal that appears in an access log as a write is a removal
        nobody can prove happened.

        Meta answers a removal in the same shape it answers an upload -
        rows received, rows refused - which is why one DTO carries both.
        """
        with session(token) as graph:
            answer = withdraw_members(
                audience_id=ref.id,
                members=members,
                token=token,
                client=graph,
                dry_run=dry_run,
            )
        return self._upload(ref, answer, dry_run=dry_run)

    def delete_audience(
        self, *, ref: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        with session(token) as graph:
            done = remove_audience(
                audience_id=ref.id, token=token, client=graph, dry_run=dry_run
            )
        return ActionResult(ok=done, ref=ref, dry_run=dry_run)

    @staticmethod
    def _ref(external_id: str) -> ExternalRef:
        return ExternalRef(provider=PROVIDER, level="audience", id=external_id)

    @classmethod
    def _audience(cls, row: CustomAudienceRow) -> AudienceDTO:
        return AudienceDTO(
            ref=cls._ref(row.id),
            name=row.name,
            description=row.description,
            subtype_raw=row.subtype,
            accepts_members=row.accepts_members,
            can_seed=row.can_seed,
            approximate_count_lower=row.count_lower,
            approximate_count_upper=row.count_upper,
            processing=AudienceStateDTO(
                code=str(row.operation_status.code or ""),
                description=row.operation_status.description,
            ),
            readiness=AudienceStateDTO(
                code=str(row.delivery_status.code or ""),
                description=row.delivery_status.description,
            ),
            is_ready=row.is_ready,
            customer_file_source=row.customer_file_source,
            rule_raw=row.rule,
            lookalike_raw=row.lookalike_spec,
            retention_days=row.retention_days,
            created_time=row.time_created,
            updated_time=row.time_updated,
        )

    @staticmethod
    def _upload(
        ref: ExternalRef, row: MemberUploadRow, *, dry_run: bool
    ) -> MemberUploadDTO:
        return MemberUploadDTO(
            ref=ref,
            received=row.num_received,
            invalid=row.num_invalid_entries,
            session_id=row.session_id,
            invalid_samples=row.invalid_entry_samples,
            dry_run=dry_run,
        )


class MetaLeads:
    """Meta as :class:`adskit.LeadSourcePort`.

    Three calls and one omission that costs everything. ``subscribe`` is
    what makes the other two ever happen: a page nobody subscribed fills in
    its forms and tells nobody, with no error to find and no request to
    trace.

    Every method here takes the **page's** token, not the ad account's. A
    lead belongs to a form, a form belongs to a page, and the account's
    token is refused with a permission error naming the lead - which reads
    as a missing scope and is not one.
    """

    def list_forms(self, *, page: ExternalRef, token: str) -> list[LeadFormDTO]:
        """Every lead form on one page, collecting or not.

        One call for the whole page, which is what makes this affordable
        to run beside the daily sweep: the alternative - a read per form -
        would spend a call on each of the forms it is trying to find out
        about.
        """
        with session(token) as graph:
            rows = read_forms(page_id=page.id, token=token, client=graph)
        return [self._form(row) for row in rows]

    def fetch_lead(self, *, ref: ExternalRef, token: str) -> LeadDTO:
        """One lead, by the id a webhook named.

        The second half of the two-step the webhook exists for: the body
        Meta posts says only that a lead exists, never what is in it.
        """
        with session(token) as graph:
            row = read_lead(leadgen_id=ref.id, token=token, client=graph)
        return self._lead(row)

    def list_leads(
        self,
        *,
        form: ExternalRef,
        since: datetime,
        token: str,
        until: datetime | None = None,
    ) -> list[LeadDTO]:
        """Everything this form collected since ``since``.

        The reconciliation path, and not a substitute for the webhook. Meta
        counts reads against a per-page daily allowance derived from how
        many leads the page actually collected, so polling this is how an
        account with few leads runs out of the budget it needs to fetch
        them.
        """
        with session(token) as graph:
            rows = read_leads(
                form_id=form.id, since=since, until=until, token=token, client=graph
            )
        return [self._lead(row) for row in rows]

    def subscribe(
        self, *, page: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Ask Meta to start posting this page's leads to our webhook.

        Idempotent at Meta's end, so it is safe to call every time a page
        is chosen rather than tracked as a one-off - which matters, because
        a subscription can be removed from the page's own settings by
        somebody who has never heard of this product.
        """
        ok = subscribe_page(page_id=page.id, token=token, dry_run=dry_run)
        return ActionResult(
            ok=ok,
            ref=page,
            applied={"subscribed_fields": [LEADGEN_FIELD]},
            dry_run=dry_run,
        )

    @classmethod
    def _form(cls, row: LeadFormRow) -> LeadFormDTO:
        """One form as the domain holds it.

        ``status`` is collapsed to a yes-or-no here and carried raw beside
        it. This is the only place that decides which of Meta's words mean
        "still collecting", and it decides by naming the one that does -
        so a word Meta adds tomorrow reads as "not collecting" rather than
        as an unhandled state. The raw string is what an operator compares
        against Meta's own screen.
        """
        return LeadFormDTO(
            ref=ExternalRef(provider=PROVIDER, level="form", id=row.id),
            name=row.name,
            is_collecting=row.is_collecting,
            status_raw=row.status,
            leads_count=row.leads_count,
            created_time=row.created_time,
            questions_raw=row.questions,
            privacy_policy_url=row.policy_url,
            locale=row.locale,
            ending_kind=_ending_kind(row.thank_you_button),
            ending_target=row.thank_you_target,
            ending_button_text=row.thank_you_button_text,
        )

    @classmethod
    def _lead(cls, row: LeadRow) -> LeadDTO:
        """Meta's answer sheet as the domain's own.

        ``field_data`` travels whole and unparsed. The questions are the
        advertiser's, so no fixed set of columns can hold them, and the
        normalisation into a name and a phone number is the domain's job -
        it needs the country the business operates in, which this package
        has no way to know.
        """
        return LeadDTO(
            ref=ExternalRef(provider=PROVIDER, level="form", id=row.id),
            form=(
                ExternalRef(provider=PROVIDER, level="form", id=row.form_id)
                if row.form_id
                else None
            ),
            field_data=row.field_data,
            submitted_at=row.created_time,
            campaign_external_id=row.campaign_id,
            adset_external_id=row.adset_external_id,
            ad_external_id=row.ad_id,
            is_organic=row.is_organic,
        )


class MetaConversions:
    """Meta as :class:`adskit.ConversionPort`. The answer going the other way.

    The only class in this adapter that tells Meta something rather than
    asking it, and the one the product's own headline figure depends on
    meaning anything. Everything else here reads what a campaign did; this
    is what makes the campaign do something different.

    The **ad account's** token, not the page's - unlike every method on
    :class:`MetaLeads`. A lead belongs to a page and the dataset it is
    reported into belongs to the ad account, which is the seam that decides
    which credential each half of this journey travels on.

    ``test_event_code`` is configuration: set, every batch lands in Events
    Manager's «Test events» tab rather than the live dataset.
    """

    def __init__(self, *, test_event_code: str = "") -> None:
        self._test_event_code = test_event_code

    def report_leads(
        self,
        *,
        dataset: ExternalRef,
        events: Sequence[LeadEventDTO],
        token: str,
        dry_run: bool = True,
    ) -> ConversionReceiptDTO:
        """Send a batch of verdicts. Answers with Meta's own count.

        ``accepted`` is what came back rather than what went out, and the
        difference is the whole reason this returns anything. Meta answers
        200 to a batch containing leads older than its window and simply
        does not count them, so a caller reading the length of its own list
        would stamp them reported and never send them again.
        """
        with session(token) as graph:
            row = send_lead_events(
                dataset_id=dataset.id,
                events=events,
                token=token,
                client=graph,
                dry_run=dry_run,
                test_event_code=self._test_event_code,
            )

        return ConversionReceiptDTO(
            dataset=dataset,
            accepted=row.events_received,
            trace_id=row.fbtrace_id,
        )

    def report_window_days(self) -> int:
        """Meta's own limit on how late a server event may arrive."""
        return REPORT_WINDOW_DAYS


class MetaMetrics:
    """The read half of :class:`adskit.MetricsPort`.

    One call per range rather than per day: ``time_increment=1`` makes Meta
    split its own aggregate, so a ninety-day backfill is one request and not
    ninety. That matters because this shares a rate limit with lead
    retrieval, and a limit spent on history is a limit not available to a
    lead arriving now.

    Reads only. There is nothing to write here and there never will be -
    performance is something a provider reports, not something an advertiser
    sets.
    """

    def fetch_daily(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        token: str,
    ) -> list[MetricsDTO]:
        """Every day in the range, at one level of the hierarchy.

        ``level`` is refused rather than passed through when Meta has no
        such breakdown. The domain's levels include a lead form and an
        interest; asking this endpoint about either returns an error that
        reads like a bug in us.
        """
        wanted = _INSIGHT_LEVELS.get(level)
        if wanted is None:
            raise InvalidRequest(f"no daily figures at level {level!r}")

        with session(token) as graph:
            rows = fetch_insights(
                account_id=account.id,
                since=since,
                until=until,
                level=wanted,
                token=token,
                client=graph,
            )

        return [self._row(row, level=level) for row in rows if _one_day(row)]

    def fetch_breakdown(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        kind: BreakdownKind,
        token: str,
    ) -> list[SegmentMetricsDTO]:
        """The same range at one level, cut into slices.

        Both words are refused rather than passed through. A level Meta has
        no insights for and a cut it does not offer fail here by name, where
        the message says which one was wrong - not four frames later as a
        Graph error that reads like a bug in this product.

        ``parts`` is used twice and that is deliberate: the same tuple names
        the breakdowns in the request and the keys to read out of the answer,
        in the same order. Two lists would drift, and a drifted pair joins
        the gender to the age bucket the wrong way round without failing.
        """
        wanted = _INSIGHT_LEVELS.get(level)
        if wanted is None:
            raise InvalidRequest(f"no daily figures at level {level!r}")

        parts = _BREAKDOWN_PARTS.get(kind)
        if parts is None:
            raise InvalidRequest(f"no {kind!r} breakdown at this provider")

        with session(token) as graph:
            rows = read_breakdown(
                account_id=account.id,
                since=since,
                until=until,
                level=wanted,
                breakdowns=parts,
                token=token,
                client=graph,
            )

        return [
            self._segment(row, level=level, kind=kind, parts=parts)
            for row in rows
            if _one_day(row)
        ]

    def fetch_people(
        self,
        *,
        account: ExternalRef,
        ranges: Sequence[tuple[date, date]],
        level: Level,
        token: str,
    ) -> list[PeopleCountDTO]:
        """Reach and the ad recall estimate, counted once per whole range."""
        wanted = _INSIGHT_LEVELS.get(level)
        if wanted is None:
            raise InvalidRequest(f"no people counts at level {level!r}")
        if not ranges:
            return []

        with session(token) as graph:
            rows = fetch_people_counts(
                account_id=account.id,
                ranges=list(ranges),
                level=wanted,
                token=token,
                client=graph,
            )

        return [
            PeopleCountDTO(
                ref=ExternalRef(
                    provider=PROVIDER,
                    level=level,
                    id=str(row.get(_ID_FIELDS[level], "")),
                ),
                since=date.fromisoformat(str(row["date_start"])),
                until=date.fromisoformat(str(row["date_stop"])),
                campaign_external_id=str(row.get("campaign_id", "")),
                adset_external_id=str(row.get("adset_id", "")),
                ad_external_id=str(row.get("ad_id", "")),
                reach=_as_int(row.get("reach")),
                recallers=_as_int(row.get("estimated_ad_recallers")),
            )
            for row in rows
            # A row without both ends cannot say which range it answers.
            if row.get("date_start") and row.get("date_stop")
        ]

    @staticmethod
    def _segment(
        row: dict[str, object],
        *,
        level: Level,
        kind: BreakdownKind,
        parts: tuple[str, ...],
    ) -> SegmentMetricsDTO:
        """One segment row, with its spend turned into an integer.

        The slice is handed over **in pieces**. How the pieces become one
        stored value is a domain rule and lives in the domain; this package
        may not import it, and inventing a second separator here is how a
        row stops matching the row it was meant to replace.

        Whatever the provider filed the row under is kept, including the
        buckets nobody targeted. A campaign aimed at eighteen to sixty-five
        still reports a ``65+`` cell - the bucket is open-ended - and Meta
        files what it could not attribute under ``unknown``. Both are spend
        that happened, and a parser that dropped them would make the segments
        fall short of the total for a reason nothing could explain.

        The same goes for a placement nobody asked for. An ad set targeted at
        four positions can still report a fifth, because Meta moves delivery
        into adjacent inventory and reports where it actually ran; and the
        names it reports are its own - see ``_BREAKDOWN_PARTS``. A parser that
        kept only the positions in the targeting would hide exactly the spend
        somebody would want to know about.
        """
        currency = str(row.get("account_currency", ""))
        own = str(row.get(_ID_FIELDS[level], ""))

        return SegmentMetricsDTO(
            ref=ExternalRef(provider=PROVIDER, level=level, id=own),
            day=date.fromisoformat(str(row.get("date_start"))),
            kind=kind,
            segment_parts=tuple(str(row.get(part, "")) for part in parts),
            campaign_external_id=str(row.get("campaign_id", "")),
            adset_external_id=str(row.get("adset_id", "")),
            ad_external_id=str(row.get("ad_id", "")),
            spend_minor=META_MONEY.to_minor(
                amount=_as_decimal(row.get("spend")), currency=currency
            ),
            currency=currency,
            impressions=_as_int(row.get("impressions")),
            reach=_as_int(row.get("reach")),
            clicks=_as_int(row.get("clicks")),
            leads_reported=lead_count(
                row.get("actions"), goal=row.get("optimization_goal")
            ),
        )

    @staticmethod
    def _row(row: dict[str, object], *, level: Level) -> MetricsDTO:
        """One insight row, with its amounts turned into integers.

        The conversion is the whole reason this is not a passthrough. Meta
        answers spend, CPM and CPC in **whole currency** - "12.34" - while
        answering budgets on the same objects in minor units, also as
        strings. Storing one where the other was meant is a hundredfold
        error that nothing downstream can detect.
        """
        currency = str(row.get("account_currency", ""))
        own = str(row.get(f"{_ID_FIELDS[level]}", ""))
        # Where this ad set's leads are counted - on a form, or on the
        # advertiser's website. One answer per ad set rather than per day.
        leads = lead_actions_for(row.get("optimization_goal"))

        return MetricsDTO(
            ref=ExternalRef(provider=PROVIDER, level=level, id=own),
            day=date.fromisoformat(str(row.get("date_start"))),
            campaign_external_id=str(row.get("campaign_id", "")),
            adset_external_id=str(row.get("adset_id", "")),
            ad_external_id=str(row.get("ad_id", "")),
            spend_minor=META_MONEY.to_minor(
                amount=_as_decimal(row.get("spend")), currency=currency
            ),
            currency=currency,
            impressions=_as_int(row.get("impressions")),
            reach=_as_int(row.get("reach")),
            clicks=_as_int(row.get("clicks")),
            leads_reported=_as_int(action_value(row.get("actions"), leads)),
            # Read from the same array and kept apart from the count above.
            # A conversation and a form submission are both results and are
            # not the same object; added together they would put a number
            # into a cost per lead that no lead is behind.
            # Ads Manager's own "Results" where Meta sent it, which is the
            # ad set's goal and nothing else; the action list only where it
            # did not.
            results_reported=_result_of(row),
            recallers=_as_int(row.get("estimated_ad_recallers")),
            profile_visits=profile_visit_count(row.get(RESULTS_FIELD)),
            # Only where it disagrees with what this product asked for.
            # Empty means the two windows match, which is the ordinary case
            # and not something a screen should say anything about.
            attribution_setting=differing_attribution(row.get("attribution_setting")),
            frequency=_as_decimal(row.get("frequency")),
            ctr=_as_decimal(row.get("ctr")),
            cpm_minor=META_MONEY.to_minor(
                amount=_as_decimal(row.get("cpm")), currency=currency
            ),
            cpc_minor=META_MONEY.to_minor(
                amount=_as_decimal(row.get("cpc")), currency=currency
            ),
            # Absent on every level but ``ad``, where they were not asked
            # for. ``_ranking`` answers the empty string for that, which is
            # what distinguishes it from Meta saying "unknown".
            quality_ranking=_ranking(row.get("quality_ranking")),
            engagement_rate_ranking=_ranking(row.get("engagement_rate_ranking")),
            conversion_rate_ranking=_ranking(row.get("conversion_rate_ranking")),
            object_name=str(row.get(_NAME_FIELDS[level], "")),
            unique_clicks=_as_int(row.get("unique_clicks")),
            inline_link_clicks=_as_int(row.get("inline_link_clicks")),
            unique_inline_link_clicks=_as_int(row.get("unique_inline_link_clicks")),
            outbound_clicks=single_value(row.get("outbound_clicks")),
            landing_page_views=action_count(row.get("actions"), LANDING_PAGE_ACTIONS),
            video_plays=single_value(row.get("video_play_actions")),
            video_thruplays=single_value(row.get("video_thruplay_watched_actions")),
            video_p25=single_value(row.get("video_p25_watched_actions")),
            video_p50=single_value(row.get("video_p50_watched_actions")),
            video_p75=single_value(row.get("video_p75_watched_actions")),
            video_p100=single_value(row.get("video_p100_watched_actions")),
            # From ``actions``, not from ``video_play_actions``: the plays
            # array files its starts under the same ``video_view`` name, and
            # a start is not somebody who stayed three seconds.
            video_views_3s=action_count(row.get("actions"), VIDEO_VIEW_ACTIONS),
            # Out of the same array the lead count comes from, and already
            # in every response - see the names in ``insights``. Reading
            # them costs no extra request and no rate limit at all.
            reactions=action_count(row.get("actions"), REACTION_ACTIONS),
            comments=action_count(row.get("actions"), COMMENT_ACTIONS),
            shares=action_count(row.get("actions"), SHARE_ACTIONS),
            saves=action_count(row.get("actions"), SAVE_ACTIONS),
            # Both arrive keyed by action type and in whole currency, so
            # both go through the same reader as the lead count and then
            # the same conversion as the spend.
            cost_per_lead_minor=META_MONEY.to_minor(
                amount=_as_decimal(
                    action_value(row.get("cost_per_action_type"), leads)
                ),
                currency=currency,
            ),
            lead_value_minor=META_MONEY.to_minor(
                amount=_as_decimal(action_value(row.get("action_values"), leads)),
                currency=currency,
            ),
        )


def _result_of(row: dict[str, object]) -> int:
    """The row's result: Meta's results column, or the action fallback."""
    counted = meta_result_count(row.get(RESULTS_FIELD))
    return result_count(row.get("actions")) if counted is None else counted


# Which Meta breakdown answers for a domain level. A closed map rather than
# passing the word through: the domain has levels Meta's insights endpoint
# has never heard of - a lead form, an interest - and sending one returns an
# error that reads like a bug in this product.
_INSIGHT_LEVELS: dict[str, str] = {
    "account": "account",
    "campaign": "campaign",
    "adset": "adset",
    "ad": "ad",
}

# Which field carries the object's own name at each level. The row already
# names every rung above it; this is the one that matches ``ref.id``.
_NAME_FIELDS: dict[str, str] = {
    "account": "account_name",
    "campaign": "campaign_name",
    "adset": "adset_name",
    "ad": "ad_name",
}

# Which of Meta's breakdown parameters answer a domain cut, **in order**.
#
# The order is the contract. It is what the request asks for and what the
# answer is read back in, so the parts of a slice arrive the same way round
# every time - and ``25-34|female`` and ``female|25-34`` are two different
# rows that mean the same thing.
#
# ``platform_position`` travels with ``publisher_platform`` and not alone.
# Meta refuses the position on its own, and it would be the wrong question
# anyway: ``story`` is a placement on two platforms and ``feed`` is one on
# three, so a position without its platform names several different things
# at once.
#
# **The words in the answer are not the words in the targeting.** An ad set
# is targeted with ``instagram_positions: [stream]`` and its figures come
# back under ``instagram|feed``; Audience Network is targeted as ``classic``
# and reports as ``an_classic``. Nothing here translates between the two
# vocabularies - what the provider filed the row under is what is stored,
# which is the same rule the age cut follows. A caller that wants to match a
# stored slice against a targeting spec has to know that they are two
# vocabularies, and finding that out from a rule that silently never matches
# is expensive.
# ``region`` travels alone rather than with ``country``. An ad account
# here targets one country at a time and the pair would prefix every slice
# with the same word - "Uzbekistan|Tashkent" against "Tashkent" - which
# spends the stored value's width on a constant. An account that does
# advertise across borders gets region names that repeat between countries,
# which is a real limitation and a smaller one than the alternative.
_BREAKDOWN_PARTS: dict[str, tuple[str, ...]] = {
    "age_gender": ("age", "gender"),
    "platform_position": ("publisher_platform", "platform_position"),
    "region": ("region",),
}

# Which field carries the object's own id at each level.
_ID_FIELDS: dict[str, str] = {
    "account": "account_id",
    "campaign": "campaign_id",
    "adset": "adset_id",
    "ad": "ad_id",
}


def _one_day(row: dict[str, object]) -> bool:
    """Whether this row is about exactly one day, and says which.

    Two checks, and the second is what ``date_stop`` is asked for. A row
    without a start cannot be stored, deduplicated or plotted - Meta sends
    them when a range covers days an object did not exist for.

    A row whose start and stop differ is not a day at all. It cannot happen
    while ``time_increment=1`` is sent, which is exactly why it is worth
    checking: the day that parameter is dropped or ignored, every row would
    become the whole range and the table would take a quarter's spend as a
    single Tuesday. Storing the stop date in a column would be a copy of
    the start date on the largest table here; using it as a guarantee costs
    nothing and catches the one thing it could ever tell us.
    """
    start = str(row.get("date_start", "")).strip()
    if not start:
        return False

    stop = str(row.get("date_stop", "")).strip()
    return not stop or stop == start


def _as_decimal(value: object) -> Decimal:
    """Meta sends every number as a string, including the ratios."""
    if value is None:
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return Decimal(0)


class MetaConnect:
    """Meta as :class:`adskit.ConnectPort`: the consent dialog and its code.

    ``complete`` is three calls, and none of them is optional. The code
    buys a token for about an hour; the second call stretches it to about
    sixty days, and skipping it gives a connection that dies overnight. The
    third asks Meta what the token may actually do and whose it is - the
    scopes a person can narrow by unticking a box, and the Facebook account
    the one-identity-per-cabinet rule is about.

    The app's id and secret come through the constructor, so this module
    never reads the environment.
    """

    def __init__(self, *, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret

    def authorize_url(self, *, redirect_uri: str, state: str) -> str:
        return oauth_dialog_url(
            app_id=self._app_id, redirect_uri=redirect_uri, state=state
        )

    def complete(self, *, redirect_uri: str, code: str) -> GrantDTO:
        try:
            short_lived = exchange_code(
                app_id=self._app_id,
                app_secret=self._app_secret,
                redirect_uri=redirect_uri,
                code=code,
            )
            long_lived = exchange_for_long_lived(
                app_id=self._app_id,
                app_secret=self._app_secret,
                token=short_lived.access_token,
            )
            info = inspect_token(
                app_id=self._app_id,
                app_secret=self._app_secret,
                token=long_lived.access_token,
            )
        except MetaError as exc:
            raise translate_error(exc) from exc

        return GrantDTO(
            token=long_lived.access_token,
            expires_in=long_lived.expires_in,
            scopes=info.scopes,
            external_user_id=info.user_id,
        )

    def access_token(self, *, stored: str) -> str:
        """Meta's stored token is the one calls are made with."""
        return stored


def bundle(
    *, app_id: str = "", app_secret: str = "", conversions_test_code: str = ""
) -> ProviderBundle:
    """Everything Meta can do, in one object for the registry.

    All seven ports, all of them real. The app's id and secret reach the
    one port that needs them; a bundle built without them still answers
    every other port. ``ProviderBundle`` requires every one
    of them, so a half-built provider fails where it is called rather than
    as ``None`` has no attribute somewhere unrelated.
    """
    return ProviderBundle(
        campaigns=MetaCampaigns(),
        metrics=MetaMetrics(),
        leads=MetaLeads(),
        audiences=MetaAudiences(),
        audience_sources=MetaAudienceSources(),
        conversions=MetaConversions(test_event_code=conversions_test_code),
        connect=MetaConnect(app_id=app_id, app_secret=app_secret),
        # Not a port and not a call. Meta's own arithmetic for a currency's
        # smallest unit, which every budget written through the ports above
        # is denominated in and which nothing else in the project may guess
        # at. See ``metaads.money``.
        money=META_MONEY,
    )


def _ending_kind(button: str) -> FormEndingKind:
    """Meta's ``button_type`` in the domain's word for it.

    Every button this product does not build is ``"other"`` rather than
    guessed at, and a form Meta said nothing about stays empty - "no button"
    is an answer, and silence is not the same one.
    """
    if not button:
        return ""
    if button == THANK_YOU_NONE:
        return "none"
    if button == THANK_YOU_WEBSITE:
        return "website"
    if button == THANK_YOU_CALL:
        return "call"
    return "other"
