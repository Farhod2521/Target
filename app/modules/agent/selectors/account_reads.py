"""The per-group reads one night's facts are assembled from: money, cuts, adverts, landing, trends."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from adskit import MinorUnits
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign, SiteCheck
from app.modules.agent.selectors.window import end_of, start_of
from app.modules.integrations.models import AdAccount
from app.modules.leads.models import Lead, LeadForm
from app.modules.metrics.constants import NIGHTLY_BREAKDOWNS, MetricLevel
from app.modules.metrics.models import MetricsBreakdown, MetricsDaily
from core.agent import (
    AdFacts,
    AdSetFacts,
    Funnel,
    Half,
    Landing,
    Recent,
    named_audiences,
)
from core.agent.benchmark import count_in, family_of, per_of
from core.agent.facts import ctr_bp
from core.agent.usual import DayFigures, Usual, usual_level
from core.leads.phone import is_home_number
from core.metrics import SegmentFigures, Totals

M = MetricsDaily
TREND_DAYS = 3
_NO_VERDICT = ("", "", "")
_REFUSAL_CHARS = 500

Slices = dict[str, dict[str, tuple[SegmentFigures, ...]]]


def _cabinet(
    db: Session,
    *,
    owner: User,
    account: AdAccount | None,
    level: str = MetricLevel.ADSET,
) -> list[Any]:
    from app.modules.metrics.selectors.facts import cabinet_where

    return cabinet_where(db, owner=owner, level=level, account=account)


@dataclass(frozen=True, slots=True)
class Window:
    """One ad set's whole window, and the two halves of it."""

    spend_minor: int = 0
    impressions: int = 0
    clicks: int = 0
    leads_reported: int = 0
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0
    days: int = 0
    early: Half = field(default_factory=Half)
    late: Half = field(default_factory=Half)
    funnel: Funnel = field(default_factory=Funnel)


_DAY_COLUMNS = (
    "adset_external_id",
    "date",
    "spend_minor",
    "impressions",
    "clicks",
    "inline_link_clicks",
    "leads_reported",
    "results_reported",
    "recallers",
    "profile_visits",
    "frequency",
    "landing_page_views",
    "video_plays",
    "video_views_3s",
    "video_thruplays",
)


def sums_by_adset(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    account: AdAccount | None = None,
) -> dict[str, Window]:
    """``{ad set id: window}`` over the range, from the provider's own days."""
    rows = db.execute(
        select(*(getattr(M, name) for name in _DAY_COLUMNS)).where(
            *_cabinet(db, owner=owner, account=account),
            M.date >= since,
            M.date <= until,
            M.adset_external_id != "",
        )
    ).mappings()
    midpoint = since + timedelta(days=((until - since).days + 1) // 2)
    collected: dict[str, dict[str, Any]] = {}
    for row in rows:
        into = collected.setdefault(
            row["adset_external_id"], {"total": [], "early": [], "late": []}
        )
        into["total"].append(row)
        into["late" if row["date"] >= midpoint else "early"].append(row)
    return {
        external_id: Window(
            spend_minor=_sum(parts["total"], "spend_minor"),
            impressions=_sum(parts["total"], "impressions"),
            clicks=_sum(parts["total"], "clicks"),
            leads_reported=_sum(parts["total"], "leads_reported"),
            results=_sum(parts["total"], "results_reported"),
            recallers=_sum(parts["total"], "recallers"),
            profile_visits=_sum(parts["total"], "profile_visits"),
            days=len({row["date"] for row in parts["total"]}),
            early=_half(parts["early"]),
            late=_half(parts["late"]),
            funnel=_funnel(parts["total"]),
        )
        for external_id, parts in collected.items()
    }


def _funnel(rows: list[Mapping[str, Any]]) -> Funnel:
    return Funnel(
        spend_minor=_sum(rows, "spend_minor"),
        impressions=_sum(rows, "impressions"),
        link_clicks=_sum(rows, "inline_link_clicks"),
        landing_page_views=_sum(rows, "landing_page_views"),
        video_plays=_sum(rows, "video_plays"),
        video_views_3s=_sum(rows, "video_views_3s"),
        video_thruplays=_sum(rows, "video_thruplays"),
    )


def _half(rows: list[Mapping[str, Any]]) -> Half:
    return Half(
        days=len({row["date"] for row in rows}),
        impressions=_sum(rows, "impressions"),
        link_clicks=_sum(rows, "inline_link_clicks"),
    )


def _sum(rows: list[Mapping[str, Any]], column: str) -> int:
    return sum(int(row[column] or 0) for row in rows)


def slices_by_adset(
    db: Session, *, owner: User, account: AdAccount, since: date, until: date
) -> Slices:
    """Each group's cuts over the window. One grouped query per cut."""
    from app.modules.metrics.selectors.segments import breakdown_where

    b = MetricsBreakdown
    collected: dict[str, dict[str, list[SegmentFigures]]] = {}
    for kind in NIGHTLY_BREAKDOWNS:
        rows = db.execute(
            select(
                b.external_id,
                b.breakdown_value,
                func.sum(b.spend_minor),
                func.sum(b.impressions),
                func.sum(b.clicks),
                func.sum(b.leads_reported),
            )
            .where(
                *breakdown_where(db, owner=owner, kind=kind, account=account),
                b.date >= since,
                b.date <= until,
                b.external_id != "",
            )
            .group_by(b.external_id, b.breakdown_value)
        )
        for external_id, value, spend, impressions, clicks, leads in rows:
            cuts = collected.setdefault(str(external_id), {})
            cuts.setdefault(str(kind), []).append(
                SegmentFigures(
                    segment=str(value),
                    spend_minor=MinorUnits(int(spend or 0)),
                    impressions=int(impressions or 0),
                    clicks=int(clicks or 0),
                    leads_reported=int(leads or 0),
                )
            )
    return {
        adset_id: {
            kind: tuple(sorted(items, key=_by_spend)) for kind, items in cuts.items()
        }
        for adset_id, cuts in collected.items()
    }


def _by_spend(item: SegmentFigures) -> tuple[int, str]:
    return (-item.spend_minor, item.segment)


@dataclass(frozen=True, slots=True)
class _Mirrored:
    name: str
    delivery: str
    adset_id: str
    issue_codes: tuple[str, ...]
    issue_summary: str
    refusal: str
    creative_id: str


def ads_by_adset(
    db: Session, *, owner: User, account: AdAccount, since: date, until: date
) -> dict[str, tuple[AdFacts, ...]]:
    """``{ad set id: adverts}`` over the range, biggest spender first."""
    from app.modules.leads.selectors import counts_by_ad

    mirror = _mirror(db, owner=owner, account=account)
    creatives = _creatives(
        db, owner=owner, ids={item.creative_id for item in mirror.values()}
    )
    verdicts = _rankings(db, owner=owner, account=account, since=since, until=until)
    sums = {
        str(row["external_id"]): row
        for row in _ad_sums(db, owner=owner, account=account, since=since, until=until)
    }
    tzinfo = account.tzinfo()
    leads = counts_by_ad(
        db, owner=owner, since=start_of(since, tzinfo), until=end_of(until, tzinfo)
    )
    grouped: dict[str, list[AdFacts]] = {}
    for ad_id, known in mirror.items():
        row = sums.get(ad_id)
        if row is None and known.delivery == Delivery.FINISHED:
            continue
        grouped.setdefault(known.adset_id, []).append(
            _ad_facts(
                ad_id=ad_id,
                known=known,
                row=row or {},
                creative=creatives.get(known.creative_id, {}),
                verdict=verdicts.get(ad_id, _NO_VERDICT),
                leads=leads.get(ad_id, (0, 0))[0],
            )
        )
    return {
        adset_id: tuple(
            sorted(items, key=lambda ad: (-ad.figures.spend_minor, ad.external_id))
        )
        for adset_id, items in grouped.items()
    }


def _ad_facts(
    *,
    ad_id: str,
    known: _Mirrored,
    row: Mapping[str, Any],
    creative: dict[str, str],
    verdict: tuple[str, str, str],
    leads: int,
) -> AdFacts:
    quality, engagement, conversion = verdict
    return AdFacts(
        name=known.name,
        delivery=known.delivery,
        figures=SegmentFigures(
            segment=ad_id,
            spend_minor=int(row.get("spend_minor") or 0),
            impressions=int(row.get("impressions") or 0),
            clicks=int(row.get("clicks") or 0),
            leads_reported=int(row.get("leads_reported") or 0),
        ),
        days_with_spend=int(row.get("days") or 0),
        quality_ranking=quality,
        engagement_ranking=engagement,
        conversion_ranking=conversion,
        issue_codes=known.issue_codes,
        issue_summary=known.issue_summary,
        refusal=known.refusal,
        creative_kind=creative.get("kind", ""),
        image_hash=creative.get("image_hash", ""),
        video_id=creative.get("video_id", ""),
        headline=creative.get("headline", ""),
        message=creative.get("message", ""),
        link_clicks=int(row.get("link_clicks") or 0),
        landing_page_views=int(row.get("landing_page_views") or 0),
        video_views_3s=int(row.get("video_views_3s") or 0),
        leads=leads,
    )


def _ad_sums(
    db: Session, *, owner: User, account: AdAccount, since: date, until: date
) -> list[Mapping[str, Any]]:
    return list(
        db.execute(
            select(
                M.external_id,
                func.sum(M.spend_minor).label("spend_minor"),
                func.sum(M.impressions).label("impressions"),
                func.sum(M.clicks).label("clicks"),
                func.sum(M.leads_reported).label("leads_reported"),
                func.sum(M.inline_link_clicks).label("link_clicks"),
                func.sum(M.landing_page_views).label("landing_page_views"),
                func.sum(M.video_views_3s).label("video_views_3s"),
                func.count(func.distinct(M.date)).label("days"),
            )
            .where(
                *_cabinet(db, owner=owner, account=account, level=MetricLevel.AD),
                M.date >= since,
                M.date <= until,
            )
            .group_by(M.external_id)
        ).mappings()
    )


def _rankings(
    db: Session, *, owner: User, account: AdAccount, since: date, until: date
) -> dict[str, tuple[str, str, str]]:
    from app.modules.metrics.selectors.creative_rankings import RANKING_DAYS

    first = max(since, until - timedelta(days=RANKING_DAYS - 1))
    rows = db.execute(
        select(
            M.external_id,
            M.quality_ranking,
            M.engagement_rate_ranking,
            M.conversion_rate_ranking,
        )
        .where(
            *_cabinet(db, owner=owner, account=account, level=MetricLevel.AD),
            M.date >= first,
            M.date <= until,
            M.quality_ranking != "",
        )
        .order_by(M.date.desc())
    )
    found: dict[str, tuple[str, str, str]] = {}
    for external_id, quality, engagement, conversion in rows:
        found.setdefault(
            str(external_id), (str(quality), str(engagement), str(conversion))
        )
    return found


def _mirror(db: Session, *, owner: User, account: AdAccount) -> dict[str, _Mirrored]:
    rows = db.execute(
        select(
            Ad.external_id,
            Ad.name,
            Ad.delivery,
            AdSet.external_id,
            Ad.issue_codes,
            Ad.issue_summary,
            Ad.review_feedback,
            Ad.creative_external_id,
        )
        .join(AdSet, AdSet.id == Ad.adset_id)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(Ad.owner_id == owner.id, Campaign.ad_account_id == account.id)
    )
    return {
        str(external_id): _Mirrored(
            name=str(name or ""),
            delivery=str(delivery or Delivery.UNKNOWN),
            adset_id=str(adset_id or ""),
            issue_codes=tuple(str(code) for code in codes or ()),
            issue_summary=str(summary or ""),
            refusal=refusal_of(feedback),
            creative_id=str(creative_id or ""),
        )
        for external_id, name, delivery, adset_id, codes, summary, feedback, creative_id in rows
    }


def _creatives(db: Session, *, owner: User, ids: set[str]) -> dict[str, dict[str, str]]:
    wanted = {value for value in ids if value}
    if not wanted:
        return {}
    keys = ("kind", "image_hash", "video_id", "headline", "message")
    return {
        row.external_id: {key: str(getattr(row, key) or "") for key in keys}
        for row in db.scalars(
            select(AdCreative).where(
                AdCreative.owner_id == owner.id, AdCreative.external_id.in_(wanted)
            )
        )
    }


def refusal_of(feedback: object) -> str:
    """The provider's refusal as one line per policy, or blank."""
    overall = feedback.get("overall") if isinstance(feedback, dict) else None
    if not isinstance(overall, dict):
        return ""
    lines = [
        f"{policy}: {reason}".strip()
        for policy, reason in overall.items()
        if str(reason or "").strip()
    ]
    return "\n".join(lines)[:_REFUSAL_CHARS]


def audiences_we_hold(db: Session, *, owner: User) -> frozenset[str] | None:
    """Every saved audience of this owner's the mirror knows about."""
    from app.modules.integrations.selectors import audiences

    found = frozenset(
        str(row.external_id) for row in audiences(db, owner=owner) if row.external_id
    )
    return found or None


def unusable_in(
    *, targeting: Mapping[str, Any] | None, held: frozenset[str] | None
) -> tuple[str, ...]:
    """The audiences this group is aimed at that no longer exist."""
    if held is None:
        return ()
    return tuple(
        external_id
        for external_id in named_audiences(targeting or {})
        if external_id not in held
    )


def junk_by_adset(
    db: Session, *, owner: User, adset_ids: list[str], since: datetime, until: datetime
) -> dict[str, int]:
    """``{group: enquiries in the window nobody can usefully call}``."""
    from app.modules.businesses.models import Business

    if not adset_ids:
        return {}
    regions = frozenset(
        code.upper()
        for code in db.scalars(
            select(Business.country_code).where(Business.user_id == owner.id)
        )
        if code
    )
    rows = list(
        db.execute(
            select(Lead.id, Lead.adset_external_id, Lead.phone_e164, Lead.submitted_at)
            .where(
                Lead.owner_id == owner.id,
                Lead.adset_external_id.in_(adset_ids),
                Lead.submitted_at >= since,
                Lead.submitted_at <= until,
            )
            .order_by(Lead.submitted_at)
        )
    )
    if not rows:
        return {}
    phones = {phone for _pk, _g, phone, _at in rows if phone}
    first_seen: dict[str, Any] = {}
    if phones:
        first_seen = dict(
            db.execute(
                select(Lead.phone_e164, Lead.id)
                .where(Lead.owner_id == owner.id, Lead.phone_e164.in_(phones))
                .order_by(Lead.submitted_at.desc())
            ).all()
        )
    found: Counter[str] = Counter()
    for pk, adset_id, phone, _at in rows:
        if (
            not is_home_number(e164=phone, regions=regions)
            or first_seen.get(phone) != pk
        ):
            found[adset_id] += 1
    return dict(found)


def landing_by_adset(
    db: Session, *, owner: User, account: AdAccount
) -> dict[str, Landing]:
    """``{ad set id: what its delivering adverts land on}``."""
    from app.modules.leads.selectors import forms_by_external_id

    adverts = [
        (str(adset_id), str(creative_id), str(form_id))
        for adset_id, creative_id, form_id in db.execute(
            select(AdSet.external_id, Ad.creative_external_id, Ad.lead_form_external_id)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                Ad.owner_id == owner.id,
                Campaign.ad_account_id == account.id,
                Ad.delivery == Delivery.ACTIVE,
            )
        )
    ]
    links = _links(
        db,
        owner=owner,
        creative_ids={creative for _, creative, _ in adverts if creative},
    )
    pages = {
        row.url: row
        for row in db.scalars(select(SiteCheck).where(SiteCheck.owner_id == owner.id))
    }
    forms = forms_by_external_id(
        db,
        owner=owner,
        provider=account.provider,
        external_ids=sorted({form for _, _, form in adverts if form}),
    )
    grouped: dict[str, list[tuple[str, str]]] = {}
    for adset_id, creative_id, form_id in adverts:
        grouped.setdefault(adset_id, []).append((links.get(creative_id, ""), form_id))
    return {
        adset_id: _landing(entries, pages=pages, forms=forms)
        for adset_id, entries in grouped.items()
    }


def _landing(
    entries: list[tuple[str, str]],
    *,
    pages: dict[str, SiteCheck],
    forms: dict[str, LeadForm],
) -> Landing:
    looked = [pages[url] for url, _ in entries if url in pages]
    questions = [
        len(forms[form].questions_raw)
        for _, form in entries
        if form in forms and isinstance(forms[form].questions_raw, list)
    ]
    return Landing(
        down_urls=tuple(sorted({row.url for row in looked if row.is_down})),
        pixel_seen=any(row.meta_pixel_ids for row in looked),
        form_questions=max(questions, default=0),
    )


def _links(db: Session, *, owner: User, creative_ids: set[str]) -> dict[str, str]:
    if not creative_ids:
        return {}
    return {
        str(external_id): str(link_url)
        for external_id, link_url in db.execute(
            select(AdCreative.external_id, AdCreative.link_url).where(
                AdCreative.owner_id == owner.id,
                AdCreative.external_id.in_(creative_ids),
                AdCreative.link_url != "",
            )
        )
    }


def recent_by_adset(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    adset_ids: Iterable[str],
    until: date,
) -> dict[str, Recent]:
    """``{group: its last three finished days}``, results counted both ways."""
    from app.modules.leads.selectors import counts_by_adset

    ids = list(adset_ids)
    if not ids:
        return {}
    since = until - timedelta(days=TREND_DAYS - 1)
    tzinfo = account.tzinfo()
    ours = counts_by_adset(
        db, owner=owner, since=start_of(since, tzinfo), until=end_of(until, tzinfo)
    )
    rows = db.execute(
        select(
            M.adset_external_id,
            func.sum(M.spend_minor).label("spend"),
            func.sum(M.impressions).label("shown"),
            func.sum(M.inline_link_clicks).label("clicks"),
            func.sum(M.leads_reported).label("reported"),
            func.sum(M.results_reported).label("results"),
            func.sum(M.recallers).label("recallers"),
            func.sum(M.profile_visits).label("visits"),
        )
        .where(
            *_cabinet(db, owner=owner, account=account),
            M.date >= since,
            M.date <= until,
            M.adset_external_id.in_(ids),
        )
        .group_by(M.adset_external_id)
    ).mappings()
    return {
        row["adset_external_id"]: Recent(
            days=TREND_DAYS,
            link_clicks=int(row["clicks"] or 0),
            totals=Totals(
                spend_minor=int(row["spend"] or 0),
                impressions=int(row["shown"] or 0),
                leads=ours.get(row["adset_external_id"], (0, 0))[0],
                leads_reported=int(row["reported"] or 0),
                results=int(row["results"] or 0),
                recallers=int(row["recallers"] or 0),
                profile_visits=int(row["visits"] or 0),
            ),
        )
        for row in rows
    }


def launch_ctr_by_adset(
    db: Session, *, owner: User, account: AdAccount, adset_ids: Iterable[str]
) -> dict[str, int]:
    """``{group: link click-through rate over its first three days with spend}``."""
    ids = list(adset_ids)
    if not ids:
        return {}
    base = [
        *_cabinet(db, owner=owner, account=account),
        M.adset_external_id.in_(ids),
        M.spend_minor > 0,
    ]
    first = dict(
        db.execute(
            select(M.adset_external_id, func.min(M.date))
            .where(*base)
            .group_by(M.adset_external_id)
        ).all()
    )
    if not first:
        return {}
    window = or_(
        *(
            and_(
                M.adset_external_id == adset_id,
                M.date <= day + timedelta(days=TREND_DAYS - 1),
            )
            for adset_id, day in first.items()
        )
    )
    summed: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for adset_id, shown, clicks in db.execute(
        select(
            M.adset_external_id, func.sum(M.impressions), func.sum(M.inline_link_clicks)
        )
        .where(*base, window)
        .group_by(M.adset_external_id)
    ):
        summed[adset_id] = [int(shown or 0), int(clicks or 0)]
    return {
        adset_id: rate
        for adset_id, (shown, clicks) in summed.items()
        if (rate := ctr_bp(clicks=clicks, impressions=shown)) is not None
    }


_USUAL_COLUMNS = (
    "adset_external_id",
    "date",
    "spend_minor",
    "impressions",
    "inline_link_clicks",
    "leads_reported",
    "results_reported",
    "recallers",
    "profile_visits",
    "video_plays",
    "video_views_3s",
)


def usual_levels(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    adsets: tuple[AdSetFacts, ...],
    until: date,
    days: int,
) -> dict[str, Usual]:
    """``{family: the pair's usual level}`` over ``days`` ending ``until``."""
    from app.modules.leads.selectors import adset_days

    families = {item.external_id: family_of(item) for item in adsets}
    if not families:
        return {}
    since = until - timedelta(days=days - 1)
    tzinfo = account.tzinfo()
    rows = db.execute(
        select(*(getattr(M, name) for name in _USUAL_COLUMNS)).where(
            *_cabinet(db, owner=owner, account=account),
            M.date >= since,
            M.date <= until,
            M.adset_external_id.in_(list(families)),
        )
    ).mappings()
    ours = adset_days(
        db,
        owner=owner,
        since=start_of(since, tzinfo),
        until=end_of(until, tzinfo),
        tzinfo=tzinfo,
    )
    by_day: dict[str, dict[date, list[DayFigures]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        family = families[row["adset_external_id"]]
        leads = ours.get((row["adset_external_id"], row["date"]), 0)
        by_day[family][row["date"]].append(_usual_day(row, family=family, leads=leads))
    return {
        family: usual_level(
            [_summed(parts) for parts in found.values()], per=per_of(family)
        )
        for family, found in by_day.items()
    }


def _usual_day(row: Mapping[str, Any], *, family: str, leads: int) -> DayFigures:
    impressions = int(row["impressions"] or 0)
    video = int(row["video_plays"] or 0) > 0
    totals = Totals(
        spend_minor=int(row["spend_minor"] or 0),
        impressions=impressions,
        leads=leads,
        leads_reported=int(row["leads_reported"] or 0),
        results=int(row["results_reported"] or 0),
        recallers=int(row["recallers"] or 0),
        profile_visits=int(row["profile_visits"] or 0),
    )
    link_clicks = int(row["inline_link_clicks"] or 0)
    return DayFigures(
        spend_minor=totals.spend_minor,
        impressions=impressions,
        link_clicks=link_clicks,
        results=count_in(totals=totals, link_clicks=link_clicks, family=family) or 0,
        video_impressions=impressions if video else 0,
        video_views_3s=int(row["video_views_3s"] or 0) if video else 0,
    )


def _summed(parts: list[DayFigures]) -> DayFigures:
    return DayFigures(
        spend_minor=sum(part.spend_minor for part in parts),
        impressions=sum(part.impressions for part in parts),
        link_clicks=sum(part.link_clicks for part in parts),
        results=sum(part.results for part in parts),
        video_impressions=sum(part.video_impressions for part in parts),
        video_views_3s=sum(part.video_views_3s for part in parts),
    )


__all__ = [
    "TREND_DAYS",
    "Slices",
    "Window",
    "ads_by_adset",
    "audiences_we_hold",
    "junk_by_adset",
    "landing_by_adset",
    "launch_ctr_by_adset",
    "recent_by_adset",
    "refusal_of",
    "slices_by_adset",
    "sums_by_adset",
    "unusable_in",
    "usual_levels",
]
