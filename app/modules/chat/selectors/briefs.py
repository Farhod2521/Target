"""Groups, adverts, forms and pages, in the words and figures an answer needs."""

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from adskit import ExternalRef
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.campaign_row import audience_line
from app.modules.ads.constants import NOT_LIVE, Delivery
from app.modules.ads.models import Ad, AdCreative, AdSet, SiteCheck
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.figures import bp_percent, decimal_of
from app.modules.agent.models import AdSetDiagnosis
from app.modules.chat.constants import AD_WORDS_CHARS, CONTEXT_WINDOW_DAYS
from app.modules.chat.selectors.readings import advice_of, diagnoses_for, reading_of
from app.modules.chat.selectors.result_counts import figure_sums, group_result
from app.modules.chat.selectors.scope import current_page_scope, lead_window
from app.modules.leads.models import Lead, LeadForm
from app.modules.metrics.constants import MetricLevel, Ranking
from app.modules.metrics.models import MetricsDaily
from core.agent.funnel import per_ten_thousand
from core.chat.rungs import AdDigest, AdSetDigest, FormDigest, PageDigest
from core.targeting import describe

BRIEF_DAYS = CONTEXT_WINDOW_DAYS
_RATINGS = ("quality", "engagement", "results")
_PAGE_CHARS = 120


def _costed_leads(owner: User) -> list[Any]:
    from app.modules.leads.selectors import priced

    return [Lead.owner_id == owner.id, Lead.is_test.is_(False), priced()]


def adset_brief(
    db: Session,
    *,
    owner: User,
    ref: ExternalRef,
    today: date | None = None,
    scope: PageScope | None = None,
) -> AdSetDigest | None:
    """What is worth knowing about one group, or nothing if we hold none."""
    adset_id = _group_of(db, owner=owner, ref=ref)
    if not adset_id:
        return None
    scope = scope or current_page_scope(db, owner=owner)
    if not scope.allows_adset(adset_id):
        return None
    row = db.scalar(
        select(AdSet).where(
            AdSet.owner_id == owner.id,
            AdSet.provider == ref.provider,
            AdSet.external_id == adset_id,
        )
    )
    if row is None:
        return None

    until = today or date.today()
    since = until - timedelta(days=BRIEF_DAYS - 1)
    figures = (
        db.execute(
            select(*figure_sums()).where(
                MetricsDaily.owner_id == owner.id,
                MetricsDaily.level == MetricLevel.ADSET,
                MetricsDaily.adset_external_id == adset_id,
                MetricsDaily.date >= since,
            )
        )
        .mappings()
        .one()
    )
    start, end = lead_window(db, owner=owner, since=since, until=until)
    leads = (
        db.scalar(
            select(func.count(Lead.id)).where(
                *_costed_leads(owner),
                Lead.adset_external_id == adset_id,
                Lead.submitted_at >= start,
                Lead.submitted_at <= end,
            )
        )
        or 0
    )
    return group_digest(
        row=row,
        figures=figures,
        leads=leads,
        diagnosis=diagnoses_for(db, owner=owner, adset_ids=[adset_id]).get(adset_id),
        page=scope.name_of(scope.page_of.get(adset_id, "")),
    )


def _group_of(db: Session, *, owner: User, ref: ExternalRef) -> str:
    if ref.level == "adset":
        return ref.id
    if ref.level != "ad":
        return ""
    return str(
        db.scalar(
            select(AdSet.external_id)
            .join(Ad, Ad.adset_id == AdSet.id)
            .where(
                Ad.owner_id == owner.id,
                Ad.provider == ref.provider,
                Ad.external_id == ref.id,
            )
            .limit(1)
        )
        or ""
    )


def account_adsets(
    db: Session,
    *,
    owner: User,
    limit: int,
    scope: PageScope,
    today: date | None = None,
) -> tuple[AdSetDigest, ...]:
    """The groups worth naming in an answer about groups, biggest spender first."""
    until = today or date.today()
    since = until - timedelta(days=BRIEF_DAYS - 1)
    if not scope.adset_ids:
        return ()
    spent = (
        db.execute(
            select(MetricsDaily.adset_external_id, *figure_sums())
            .where(
                MetricsDaily.owner_id == owner.id,
                MetricsDaily.level == MetricLevel.ADSET,
                MetricsDaily.date >= since,
                MetricsDaily.adset_external_id.in_(list(scope.adset_ids)),
            )
            .group_by(MetricsDaily.adset_external_id)
            .order_by(func.sum(MetricsDaily.spend_minor).desc().nulls_last())
            .limit(limit)
        )
        .mappings()
        .all()
    )
    spend_by_id = {row["adset_external_id"]: row for row in spent}
    if not spend_by_id:
        return ()
    leads_by_id = _leads_by_id(
        db, owner=owner, external_ids=spend_by_id, since=since, until=until
    )
    rows = {
        row.external_id: row
        for row in db.scalars(
            select(AdSet).where(
                AdSet.owner_id == owner.id, AdSet.external_id.in_(list(spend_by_id))
            )
        )
    }
    diagnosed = diagnoses_for(db, owner=owner, adset_ids=rows)
    return tuple(
        group_digest(
            row=rows[external_id],
            figures=figures,
            leads=leads_by_id.get(external_id, 0),
            diagnosis=diagnosed.get(external_id),
            page=scope.name_of(scope.page_of.get(external_id, "")),
        )
        for external_id, figures in spend_by_id.items()
        if external_id in rows
    )


def _leads_by_id(
    db: Session, *, owner: User, external_ids: Iterable[str], since: date, until: date
) -> dict[str, int]:
    start, end = lead_window(db, owner=owner, since=since, until=until)
    rows = db.execute(
        select(Lead.adset_external_id, func.count(Lead.id))
        .where(
            *_costed_leads(owner),
            Lead.adset_external_id.in_(list(external_ids)),
            Lead.submitted_at >= start,
            Lead.submitted_at <= end,
        )
        .group_by(Lead.adset_external_id)
    )
    return {adset_id: count for adset_id, count in rows}


def group_digest(
    *,
    row: AdSet,
    figures: Mapping[str, Any],
    leads: int,
    diagnosis: AdSetDiagnosis | None,
    page: str = "",
) -> AdSetDigest:
    """One group as the assistant reads it. The one place this is assembled."""
    currency = row.campaign.currency
    reading = reading_of(diagnosis, currency=currency)
    return AdSetDigest(
        name=row.name or row.external_id,
        campaign=row.campaign.name or row.campaign.external_id,
        page=page,
        status=str(delivery_label(row.delivery)),
        is_off=row.delivery in NOT_LIVE,
        spend=format_minor(
            amount_minor=int(figures.get("spend") or 0), currency=currency
        ),
        result=group_result(
            goal=row.optimization_goal_raw,
            promoted=row.promoted_object_raw,
            figures=figures,
            leads=leads,
            currency=currency,
        ),
        audience=str(audience_line(describe(row.targeting_raw))),
        trouble=row.issue_summary,
        cause=reading.cause,
        shown_cost=reading.shown_cost,
        click_rate=reading.click_rate,
        frequency=reading.frequency,
        costly_slice=reading.costly_slice,
        is_learning=row.is_learning,
        advice=advice_of(row.recommendations),
    )


def delivery_label(delivery: str) -> object:
    """The delivery state in the owner's words, whatever the column holds."""
    try:
        return Delivery(delivery).label
    except ValueError:
        return Delivery.UNKNOWN.label


def account_ads(
    db: Session,
    *,
    owner: User,
    limit: int,
    scope: PageScope,
    today: date | None = None,
) -> tuple[AdDigest, ...]:
    """The adverts that spent the most over the window, with their words."""
    until = today or date.today()
    since = until - timedelta(days=BRIEF_DAYS - 1)
    spent = _ads_spent(db, owner=owner, since=since, limit=limit, scope=scope)
    if not spent:
        return ()
    adverts = {
        row.external_id: row
        for row in db.scalars(
            select(Ad).where(Ad.owner_id == owner.id, Ad.external_id.in_(list(spent)))
        )
    }
    ids = [ad_id for ad_id in spent if ad_id in adverts]
    creatives = _creatives(
        db, owner=owner, ids={ad.creative_external_id for ad in adverts.values()}
    )
    forms = _form_names(
        db, owner=owner, ids={ad.lead_form_external_id for ad in adverts.values()}
    )
    leads = _leads_by_ad(db, owner=owner, ids=ids, since=since, until=until)
    ratings = _ratings(db, owner=owner, ids=ids)
    return tuple(
        _ad_digest(
            ad=adverts[ad_id],
            figures=spent[ad_id],
            creative=creatives.get(adverts[ad_id].creative_external_id),
            forms=forms,
            leads=leads.get(ad_id, 0),
            ratings=ratings.get(ad_id, ""),
        )
        for ad_id in ids
    )


def _ads_spent(
    db: Session, *, owner: User, since: date, limit: int, scope: PageScope
) -> dict[str, Mapping[str, Any]]:
    if not scope.adset_ids:
        return {}
    rows = (
        db.execute(
            select(
                MetricsDaily.ad_external_id,
                MetricsDaily.currency,
                *figure_sums(),
                func.sum(MetricsDaily.inline_link_clicks).label("clicks"),
                func.sum(MetricsDaily.video_views_3s).label("hooked"),
            )
            .where(
                MetricsDaily.owner_id == owner.id,
                MetricsDaily.level == MetricLevel.AD,
                MetricsDaily.date >= since,
                MetricsDaily.adset_external_id.in_(list(scope.adset_ids)),
                MetricsDaily.ad_external_id != "",
            )
            .group_by(MetricsDaily.ad_external_id, MetricsDaily.currency)
            .order_by(func.sum(MetricsDaily.spend_minor).desc().nulls_last())
            .limit(limit)
        )
        .mappings()
        .all()
    )
    return {str(row["ad_external_id"]): row for row in rows}


def _ad_digest(
    *,
    ad: Ad,
    figures: Mapping[str, Any],
    creative: AdCreative | None,
    forms: dict[str, str],
    leads: int,
    ratings: str,
) -> AdDigest:
    currency = str(figures["currency"])
    spend = int(figures["spend"] or 0)
    shown = int(figures["shown"] or 0)
    rate = per_ten_thousand(part=int(figures["clicks"] or 0), whole=shown)
    hooked = int(figures["hooked"] or 0)
    hook = per_ten_thousand(part=hooked, whole=shown) if hooked else None
    return AdDigest(
        name=ad.name or ad.external_id,
        group=ad.adset.name or ad.adset.external_id,
        status=str(delivery_label(ad.delivery)),
        is_off=ad.delivery in NOT_LIVE or ad.adset.delivery in NOT_LIVE,
        spend=format_minor(amount_minor=spend, currency=currency),
        result=group_result(
            goal=ad.adset.optimization_goal_raw,
            promoted=ad.adset.promoted_object_raw,
            figures=figures,
            leads=leads,
            currency=currency,
        ),
        click_rate=decimal_of(rate, 10) if rate is not None else "",
        hook=bp_percent(hook) if hook is not None else "",
        ratings=ratings,
        headline=_trimmed(creative.headline if creative else "", AD_WORDS_CHARS),
        words=_trimmed(creative.message if creative else "", AD_WORDS_CHARS),
        form=forms.get(ad.lead_form_external_id, ""),
        page=_trimmed(creative.link_url if creative else "", _PAGE_CHARS),
    )


def _creatives(
    db: Session, *, owner: User, ids: Iterable[str]
) -> dict[str, AdCreative]:
    wanted = [each for each in ids if each]
    if not wanted:
        return {}
    return {
        row.external_id: row
        for row in db.scalars(
            select(AdCreative).where(
                AdCreative.owner_id == owner.id, AdCreative.external_id.in_(wanted)
            )
        )
    }


def _form_names(db: Session, *, owner: User, ids: Iterable[str]) -> dict[str, str]:
    wanted = [each for each in ids if each]
    if not wanted:
        return {}
    return {
        str(external_id): str(name or external_id)
        for external_id, name in db.execute(
            select(LeadForm.external_id, LeadForm.name).where(
                LeadForm.owner_id == owner.id, LeadForm.external_id.in_(wanted)
            )
        )
    }


def _leads_by_ad(
    db: Session, *, owner: User, ids: list[str], since: date, until: date
) -> dict[str, int]:
    if not ids:
        return {}
    start, end = lead_window(db, owner=owner, since=since, until=until)
    rows = db.execute(
        select(Lead.ad_external_id, func.count(Lead.id))
        .where(
            *_costed_leads(owner),
            Lead.ad_external_id.in_(ids),
            Lead.submitted_at >= start,
            Lead.submitted_at <= end,
        )
        .group_by(Lead.ad_external_id)
    )
    return {str(ad_id): int(count) for ad_id, count in rows}


def _ratings(db: Session, *, owner: User, ids: list[str]) -> dict[str, str]:
    """The provider's latest verdicts on each advert, in the product's words."""
    if not ids:
        return {}
    rows = db.execute(
        select(
            MetricsDaily.ad_external_id,
            MetricsDaily.quality_ranking,
            MetricsDaily.engagement_rate_ranking,
            MetricsDaily.conversion_rate_ranking,
        )
        .where(
            MetricsDaily.owner_id == owner.id,
            MetricsDaily.level == MetricLevel.AD,
            MetricsDaily.ad_external_id.in_(ids),
            MetricsDaily.quality_ranking != "",
        )
        .order_by(MetricsDaily.ad_external_id, MetricsDaily.date.desc())
        .ext(distinct_on(MetricsDaily.ad_external_id))
    )
    return {str(ad_id): _rated(list(values)) for ad_id, *values in rows}


def _rated(values: list[str]) -> str:
    return " / ".join(
        f"{step} {Ranking(value).label}"
        for step, value in zip(_RATINGS, values, strict=True)
        if value in Ranking.values and value != Ranking.UNKNOWN
    )


def _trimmed(text: str, limit: int) -> str:
    """One line, no double quotes, and no longer than ``limit``."""
    flat = " ".join(str(text).split()).replace('"', "'")
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3].rstrip() + "..."


def account_forms(
    db: Session, *, owner: User, limit: int, scope: PageScope
) -> tuple[FormDigest, ...]:
    """The forms delivering adverts collect through, the most used first."""
    from app.modules.leads.selectors import question_summary

    if not scope.adset_ids:
        return ()
    adverts = func.count(Ad.id)
    used = db.execute(
        select(Ad.lead_form_external_id, adverts)
        .join(AdSet, AdSet.id == Ad.adset_id)
        .where(
            Ad.owner_id == owner.id,
            Ad.delivery == Delivery.ACTIVE,
            AdSet.external_id.in_(list(scope.adset_ids)),
            Ad.lead_form_external_id != "",
        )
        .group_by(Ad.lead_form_external_id)
        .order_by(adverts.desc(), Ad.lead_form_external_id)
        .limit(limit)
    )
    ids = [str(form_id) for form_id, _count in used]
    if not ids:
        return ()
    rows = {
        row.external_id: row
        for row in db.scalars(
            select(LeadForm).where(
                LeadForm.owner_id == owner.id, LeadForm.external_id.in_(ids)
            )
        )
    }
    return tuple(
        FormDigest(
            name=rows[each].name or each,
            questions=question_summary(rows[each].questions_raw),
        )
        for each in ids
        if each in rows
    )


def account_pages(db: Session, *, owner: User, limit: int) -> tuple[PageDigest, ...]:
    """The pages delivering adverts link to, a page that does not open first."""
    from app.modules.ads.constants import SiteOutcome

    rows = db.scalars(
        select(SiteCheck)
        .where(SiteCheck.owner_id == owner.id)
        .order_by(SiteCheck.is_down.desc(), SiteCheck.url)
        .limit(limit)
    )
    return tuple(
        PageDigest(
            url=row.url,
            state=str(SiteOutcome(row.outcome).label) if row.outcome else "",
            has_pixel=bool(row.meta_pixel_ids),
        )
        for row in rows
    )


__all__ = [
    "BRIEF_DAYS",
    "account_ads",
    "account_adsets",
    "account_forms",
    "account_pages",
    "adset_brief",
    "delivery_label",
    "group_digest",
]
