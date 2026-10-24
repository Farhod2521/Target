"""Meta, expressed as the ports the rest of the system talks to."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from adskit.dto import (
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
from metaads.writes import set_budget as write_budget
from metaads.writes import set_end_time as write_end_time
from metaads.writes import set_spend_cap as write_spend_cap
from metaads.writes import set_status as write_status
from metaads.writes import write_targeting

_DELIVERY: dict[str, Delivery] = {
    "ACTIVE": "active",
    "PAUSED": "paused",
    "CAMPAIGN_PAUSED": "paused_above",
    "ADSET_PAUSED": "paused_above",
    "PENDING_REVIEW": "pending",
    "PREAPPROVED": "pending",
    "PENDING_BILLING_INFO": "pending",
    "IN_PROCESS": "pending",
    "DISAPPROVED": "rejected",
    "WITH_ISSUES": "rejected",
    "ADSET_ISSUE": "rejected",
    "COMPLETED": "finished",
    "ARCHIVED": "finished",
    "DELETED": "finished",
}

_PERMISSION_CODES = frozenset({200, 294})

_NOT_FOUND_CODES = frozenset({803})

_TERMS_SUBCODES = frozenset({1815089})

_ACTION_SUBCODES = frozenset({3858385})

_BUDGET_SUBCODES = frozenset({1885272})

_PAYMENT_SUBCODES = frozenset({1359188})

_BID_SUBCODES = frozenset({1885204, 2446166})

_LOCATION_SUBCODES = frozenset({1487851})

_OVERLAP_SUBCODES = frozenset({1487756})

_PRIVACY_SUBCODES = frozenset({1892142})

_LEARNING = "LEARNING"

_RANKINGS: dict[str, Ranking] = {
    "above_average": "above_average",
    "average": "average",
    "below_average_10": "below_average_10",
    "below_average_20": "below_average_20",
    "below_average_35": "below_average_35",
    "unknown": "unknown",
}


def _ranking(value: object) -> Ranking:
    """One verdict as the domain spells it."""
    if value is None:
        return ""
    return _RANKINGS.get(str(value).strip().lower(), "unknown")


def _issues(rows: tuple[IssueRow, ...]) -> tuple[IssueDTO, ...]:
    """Meta's ``issues_info`` in domain words."""
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
    """Why an ad was refused, or ``None`` because it was not."""
    if row is None:
        return None
    return ReviewFeedbackDTO(overall=row.overall, by_placement=row.placement_specific)


MAX_SEARCH_FALLBACK = 8

_GEO_KINDS: dict[str, GeoKind] = {
    "city": "city",
    "region": "region",
    "country": "country",
}

_SETTABLE: dict[str, str] = {"active": STATUS_ACTIVE, "paused": STATUS_PAUSED}


def delivery_of(effective_status: str) -> Delivery:
    """Meta's effective status in domain words."""
    return _DELIVERY.get(effective_status.upper(), "unknown")


def translate_error(exc: MetaError) -> ProviderError:
    """One Meta failure as the domain's own."""
    words = _user_words(exc)
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
        if exc.subcode in _ACTION_SUBCODES:
            return AccountActionRequired(str(exc), code=str(exc.subcode or ""), **words)
        if exc.code in _PERMISSION_CODES:
            return PermissionDenied(str(exc), code=str(exc.code or ""), **words)
        return AuthFailed(str(exc), code=str(exc.code or ""), **words)
    if isinstance(exc, MetaPayloadTooLarge):
        return MediaTooLarge(str(exc), code="413")
    if isinstance(exc, MetaAPIError):
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
    """The catalogue entries this refusal says have been withdrawn."""
    return tuple(
        RetiredOptionDTO(**pair) for pair in retired_pairs(exc.user_message or "")
    )


def _user_words(exc: MetaError) -> dict[str, str]:
    """Meta's advertiser-facing pair, or nothing when it sent none."""
    return {
        "user_title": getattr(exc, "user_title", ""),
        "user_message": getattr(exc, "user_message", ""),
    }


@contextmanager
def session(token: str) -> Iterator[GraphClient]:
    """One connection for one call, and Meta's failures as the domain's."""
    graph = GraphClient(token=token)
    try:
        yield graph
    except MetaError as exc:
        raise translate_error(exc) from exc
    finally:
        graph.close()


class MetaCampaigns:
    """The read half of :class:`adskit.CampaignControlPort`."""

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
        """Read by id, so nothing else in the account can fail the read."""
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

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        """What state one object is in right now, read fresh."""
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
            delivery=delivery_of(effective),
            learning_status=learning,
            is_learning=learning.upper() == _LEARNING,
            daily_budget_minor=MinorUnits(int(budget)) if budget is not None else None,
        )

    def get_preview(
        self, *, ref: ExternalRef, ad_format: str, token: str
    ) -> AdPreviewDTO:
        """Where this ad can be seen as its audience will see it."""
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
        """Stop or start one object, at whatever level it sits."""
        meta_status = _SETTABLE.get(status.strip().lower())
        if meta_status is None:
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
        """Replace the daily budget on the object that holds it."""
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
        """Say when this ad set stops."""
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
        """The most this campaign may spend in total."""
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
        """Delete one object - and, for a campaign, everything inside it."""
        with session(token) as graph:
            ok = remove_object(
                object_id=ref.id, token=token, client=graph, dry_run=dry_run
            )

        return ActionResult(
            ok=ok, ref=ref, applied={"status": "deleted"}, dry_run=dry_run
        )

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
            delivery=delivery_of(row.effective_status),
            objective_raw=row.objective,
            daily_budget_minor=MinorUnits(budget) if budget is not None else None,
            spend_cap_minor=MinorUnits(cap) if cap is not None else None,
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
            delivery=delivery_of(row.effective_status),
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
            delivery=delivery_of(row.effective_status),
            creative_external_id=row.creative_external_id,
            creative=cls._creative(row.creative),
            lead_form_external_id=row.lead_form_external_id,
            issues=_issues(row.issues_info),
            review_feedback=_review_feedback(row.ad_review_feedback),
        )

    @classmethod
    def _creative(cls, row: CreativeRow) -> CreativeDTO | None:
        """The ad's content, or ``None`` when Meta sent none."""
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
            thumbnail_url=row.thumbnail_url or row.image_url,
            page_id=row.page_id,
            instagram_user_id=row.instagram_user_id,
            post_external_id=row.post_id,
            story_raw=row.object_story_spec,
        )


class MetaAudiences:
    """Who an ad set is shown to: found, measured, and replaced."""

    def find_interests(self, *, names: list[str], token: str) -> list[InterestDTO]:
        """Words in, targetable interests out. Two endpoints, one promise."""
        if not names:
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
        """Names in, rows of one closed catalogue out."""
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
        self, *, query: str, country_code: str, token: str
    ) -> list[LocationDTO]:
        """One word in, the places Meta would accept it as, out."""
        if not query.strip():
            return []

        with session(token) as graph:
            rows = search_locations(query=query, token=token, client=graph)

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
        """``delivery_estimate``, read as a range rather than a figure."""
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
        """Replace who this ad set is shown to."""
        with session(token) as graph:
            dropped = write_targeting(
                object_id=ref.id,
                targeting=targeting,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return ActionResult(
            ok=True,
            ref=ref,
            applied={"targeting": dict(targeting)},
            dropped=dropped,
            dry_run=dry_run,
        )

    @staticmethod
    def _interest(
        row: dict[str, object], *, kind: TraitKind = "interest"
    ) -> InterestDTO:
        """One catalogue row, read defensively."""
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
        """One geography row, in the domain's words."""
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
            context=region or country,
            parent_id=str(row.get("region_id") or "") if kind == "city" else "",
            supports_radius=kind == "city",
        )


def _folded(value: str) -> str:
    """One name, compared the way two systems that both wrote it would."""
    return " ".join(value.split()).casefold()


def _exact_match(name: str, rows: list[dict[str, object]]) -> dict[str, object] | None:
    """The search result that *is* this name, or nothing."""
    wanted = _folded(name)
    for row in rows:
        if _folded(str(row.get("name", ""))) == wanted and _recognised(row):
            return row
    return None


def _recognised(row: dict[str, object]) -> bool:
    """Whether Meta claims this name at all."""
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
    """The audiences an advertiser owns, as :class:`adskit.AudienceSourcePort`."""

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
        """Create the empty container."""
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
        """Which rule audiences Meta builds. A table, not a call."""
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
        """Create an audience Meta fills from a rule."""
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
        """Create an audience of people who resemble one that already exists."""
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
        """Withdraw people from the audience, by the digests that added them."""
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
    """Meta as :class:`adskit.LeadSourcePort`."""

    def list_forms(self, *, page: ExternalRef, token: str) -> list[LeadFormDTO]:
        """Every lead form on one page, collecting or not."""
        with session(token) as graph:
            rows = read_forms(page_id=page.id, token=token, client=graph)
        return [self._form(row) for row in rows]

    def fetch_lead(self, *, ref: ExternalRef, token: str) -> LeadDTO:
        """One lead, by the id a webhook named."""
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
        """Everything this form collected since ``since``."""
        with session(token) as graph:
            rows = read_leads(
                form_id=form.id, since=since, until=until, token=token, client=graph
            )
        return [self._lead(row) for row in rows]

    def subscribe(
        self, *, page: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Ask Meta to start posting this page's leads to our webhook."""
        ok = subscribe_page(page_id=page.id, token=token, dry_run=dry_run)
        return ActionResult(
            ok=ok,
            ref=page,
            applied={"subscribed_fields": [LEADGEN_FIELD]},
            dry_run=dry_run,
        )

    @classmethod
    def _form(cls, row: LeadFormRow) -> LeadFormDTO:
        """One form as the domain holds it."""
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
        """Meta's answer sheet as the domain's own."""
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
    """Meta as :class:`adskit.ConversionPort`. The answer going the other way."""

    def report_leads(
        self,
        *,
        dataset: ExternalRef,
        events: Sequence[LeadEventDTO],
        token: str,
        dry_run: bool = True,
    ) -> ConversionReceiptDTO:
        """Send a batch of verdicts. Answers with Meta's own count."""
        with session(token) as graph:
            row = send_lead_events(
                dataset_id=dataset.id,
                events=events,
                token=token,
                client=graph,
                dry_run=dry_run,
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
    """The read half of :class:`adskit.MetricsPort`."""

    def fetch_daily(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        token: str,
    ) -> list[MetricsDTO]:
        """Every day in the range, at one level of the hierarchy."""
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
        """The same range at one level, cut into slices."""
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
        """One segment row, with its spend turned into an integer."""
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
        """One insight row, with its amounts turned into integers."""
        currency = str(row.get("account_currency", ""))
        own = str(row.get(f"{_ID_FIELDS[level]}", ""))
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
            results_reported=_result_of(row),
            recallers=_as_int(row.get("estimated_ad_recallers")),
            profile_visits=profile_visit_count(row.get(RESULTS_FIELD)),
            attribution_setting=differing_attribution(row.get("attribution_setting")),
            frequency=_as_decimal(row.get("frequency")),
            ctr=_as_decimal(row.get("ctr")),
            cpm_minor=META_MONEY.to_minor(
                amount=_as_decimal(row.get("cpm")), currency=currency
            ),
            cpc_minor=META_MONEY.to_minor(
                amount=_as_decimal(row.get("cpc")), currency=currency
            ),
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
            video_views_3s=action_count(row.get("actions"), VIDEO_VIEW_ACTIONS),
            reactions=action_count(row.get("actions"), REACTION_ACTIONS),
            comments=action_count(row.get("actions"), COMMENT_ACTIONS),
            shares=action_count(row.get("actions"), SHARE_ACTIONS),
            saves=action_count(row.get("actions"), SAVE_ACTIONS),
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


_INSIGHT_LEVELS: dict[str, str] = {
    "account": "account",
    "campaign": "campaign",
    "adset": "adset",
    "ad": "ad",
}

_NAME_FIELDS: dict[str, str] = {
    "account": "account_name",
    "campaign": "campaign_name",
    "adset": "adset_name",
    "ad": "ad_name",
}

_BREAKDOWN_PARTS: dict[str, tuple[str, ...]] = {
    "age_gender": ("age", "gender"),
    "platform_position": ("publisher_platform", "platform_position"),
    "region": ("region",),
}

_ID_FIELDS: dict[str, str] = {
    "account": "account_id",
    "campaign": "campaign_id",
    "adset": "adset_id",
    "ad": "ad_id",
}


def _one_day(row: dict[str, object]) -> bool:
    """Whether this row is about exactly one day, and says which."""
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
    """Meta as :class:`adskit.ConnectPort`: the consent dialog and its code."""

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


def bundle(*, app_id: str = "", app_secret: str = "") -> ProviderBundle:
    """Everything Meta can do, in one object for the registry."""
    return ProviderBundle(
        campaigns=MetaCampaigns(),
        metrics=MetaMetrics(),
        leads=MetaLeads(),
        audiences=MetaAudiences(),
        audience_sources=MetaAudienceSources(),
        conversions=MetaConversions(),
        connect=MetaConnect(app_id=app_id, app_secret=app_secret),
        money=META_MONEY,
    )


def _ending_kind(button: str) -> FormEndingKind:
    """Meta's ``button_type`` in the domain's word for it."""
    if not button:
        return ""
    if button == THANK_YOU_NONE:
        return "none"
    if button == THANK_YOU_WEBSITE:
        return "website"
    if button == THANK_YOU_CALL:
        return "call"
    return "other"
