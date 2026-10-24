"""The numbers screen: a period's figures, its campaigns, the segments, the
recent leads and decisions - put together from the smaller selectors."""

from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.common.dates import localtime
from app.common.db import utcnow
from app.common.money import format_minor
from app.common.phone import masked
from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import (
    BREAKDOWN_RETENTION_DAYS,
    DEFAULT_PERIOD,
    EVERY_ACCOUNT,
    RANGE_MAX_DAYS,
    RECENT_DECISIONS,
    RECENT_LEADS,
    BreakdownKind,
    MetricLevel,
    Period,
)
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.ranges import CUSTOM, Range, preset_range
from app.modules.metrics.selectors import outcome_blocks, periods
from app.modules.metrics.selectors.campaigns import campaign_meta, elsewhere_spend
from app.modules.metrics.selectors.facts import (
    EVERYTHING,
    Account,
    Scope,
    accounts_synced_at,
    cabinet_where,
    campaigns_scope,
    daily_facts,
    facts_by_campaign,
    last_synced_at,
)
from app.modules.metrics.selectors.kind_cuts import kind_cuts
from app.modules.metrics.selectors.lead_bars import (
    CITY_FROM_LEADS,
    city_bars,
    hour_bars,
)
from app.modules.metrics.selectors.lead_sources import other_currency_spend
from app.modules.metrics.selectors.scope import (
    PageCampaigns,
    form_scope,
    has_form_groups,
)
from app.modules.metrics.selectors.segments import (
    oldest_breakdown_date,
    segment_costs,
    segment_spread,
)
from app.modules.metrics.selectors.shapes import (
    Dashboard,
    Decision,
    KindCuts,
    KindView,
    LeadRow,
    SegmentBlock,
    SegmentRow,
)
from core.metrics import SegmentComparison, split_segment, total

SEGMENT_TITLES: dict[str, str] = {
    BreakdownKind.AGE_GENDER: "Kim ko'rayapti",
    BreakdownKind.PLATFORM_POSITION: "Qayerda ko'rinyapti",
    BreakdownKind.REGION: "Qaysi hududda arzon",
}
SEGMENT_LABELS: dict[str, str] = {
    "female": "ayollar",
    "male": "erkaklar",
    "unknown": "noma'lum",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "messenger": "Messenger",
    "audience_network": "hamkor ilovalar",
    "feed": "lenta",
    "profile_feed": "profil lentasi",
    "video_feeds": "video lenta",
    "story": "Stories",
    "reels": "Reels",
    "facebook_reels": "Reels",
    "instream_video": "video ichida",
    "search": "qidiruv",
    "ig_search": "qidiruv",
    "marketplace": "Marketplace",
    "explore": "Explore",
    "biz_disco_feed": "tavsiyalar",
    "right_hand_column": "o'ng ustun",
    "instant_article": "tezkor maqola",
}


def both(first: Scope, second: Scope) -> Scope:
    return lambda model: and_(first(model), second(model))


def cabinet_today(
    db: Session, *, owner: User, account: AdAccount | None = None
) -> date:
    from app.modules.integrations.selectors import active_ad_account

    account = account if account is not None else active_ad_account(db, owner=owner)
    tzinfo = account.tzinfo() if account else ZoneInfo("UTC")
    return utcnow().astimezone(tzinfo).date()


class Unread(Enum):
    TOKEN = "unread"


def dashboard(
    db: Session,
    *,
    owner: User,
    date_range: Range | None = None,
    page: PageCampaigns | None = None,
    synced_at: datetime | Unread | None = Unread.TOKEN,
) -> Dashboard:
    from app.modules.integrations.selectors import active_ad_account

    account = page.home if page is not None else active_ad_account(db, owner=owner)
    currency = account.currency if account else ""
    tzinfo = account.tzinfo() if account else ZoneInfo("UTC")
    today = cabinet_today(db, owner=owner, account=account)
    chosen = date_range or preset_range(DEFAULT_PERIOD, today=today)
    scope: Scope = page.condition if page is not None else EVERYTHING
    rows_of: Account = EVERY_ACCOUNT if page is not None else account
    comparable = chosen.days * 2 <= RANGE_MAX_DAYS
    span = daily_facts(
        db,
        owner=owner,
        since=chosen.since - timedelta(days=chosen.days if comparable else 0),
        until=chosen.until,
        tzinfo=tzinfo,
        account=rows_of,
        scope=scope,
    )
    campaign_ids = page.ids if page is not None else None
    names = campaign_meta(db, owner=owner, account=account, campaign_ids=campaign_ids)
    if isinstance(synced_at, Unread):
        synced = (
            accounts_synced_at(db, owner=owner, accounts=page.accounts)
            if page is not None
            else last_synced_at(db, owner=owner, account=account)
        )
    else:
        synced = synced_at
    period = _period(
        db,
        owner=owner,
        account=rows_of,
        span=span,
        chosen=chosen,
        comparable=comparable,
        today=today,
        tzinfo=tzinfo,
        currency=currency,
        names=names,
        scope=scope,
        read_until=synced.astimezone(tzinfo).date() if synced else None,
    )
    by_city, city_source = city_bars(
        db,
        owner=owner,
        since=chosen.since,
        until=chosen.until,
        tzinfo=tzinfo,
        account=rows_of,
        scope=scope,
    )
    by_hour = hour_bars(
        db,
        owner=owner,
        since=chosen.since,
        until=chosen.until,
        tzinfo=tzinfo,
        scope=scope,
    )
    since = today - timedelta(days=BREAKDOWN_RETENTION_DAYS - 1)
    spans = {
        str(cut): _span(
            db, owner=owner, kind=str(cut), today=today, since=since, account=rows_of
        )
        for cut in SEGMENT_TITLES
    }
    segments = _segments(
        db,
        owner=owner,
        today=today,
        currency=currency,
        account=rows_of,
        scope=both(scope, form_scope(db, owner=owner)),
        has_forms=has_form_groups(
            db, owner=owner, account=account, campaign_ids=campaign_ids
        ),
        spans=spans,
    )
    return Dashboard(
        currency=currency,
        period=period,
        leads=_recent_leads(db, owner=owner, names=names, scope=scope),
        decisions=_recent_decisions(db, owner=owner, campaign_ids=campaign_ids),
        by_city=by_city,
        by_city_source=city_source,
        by_hour=by_hour,
        segments=segments,
        cuts=_cuts(
            db,
            owner=owner,
            views=period.views,
            segments=segments,
            hours=by_hour,
            cities=by_city if city_source == CITY_FROM_LEADS else (),
            names=names,
            spans=spans,
            since=since,
            today=today,
            currency=currency,
            account=rows_of,
            scope=scope,
        ),
        has_run=_has_run(db, owner=owner, account=rows_of, today=today, scope=scope),
        elsewhere_spend=_elsewhere(
            db, owner=owner, page=page, chosen=chosen, currency=currency
        ),
        other_currency=_other_currency(db, owner=owner, page=page, chosen=chosen),
    )


def _other_currency(
    db: Session, *, owner: User, page: PageCampaigns | None, chosen: Range
) -> tuple[str, ...]:
    if page is None:
        return ()
    return tuple(
        format_minor(amount_minor=amount, currency=code)
        for code, amount in other_currency_spend(
            db, owner=owner, ids=page.foreign, since=chosen.since, until=chosen.until
        )
    )


def _elsewhere(
    db: Session,
    *,
    owner: User,
    page: PageCampaigns | None,
    chosen: Range,
    currency: str,
) -> str:
    if page is None or page.page is None:
        return ""
    amount = elsewhere_spend(
        db,
        owner=owner,
        page=page.page,
        since=chosen.since,
        until=chosen.until,
        currency=currency,
        account=page.pair_account,
    )
    return format_minor(amount_minor=amount, currency=currency) if amount else ""


def _has_run(
    db: Session, *, owner: User, account: Account, today: date, scope: Scope
) -> bool:
    return (
        db.scalar(
            select(MetricsDaily.id)
            .where(
                *cabinet_where(db, owner=owner, account=account),
                MetricsDaily.date >= today - timedelta(days=RANGE_MAX_DAYS - 1),
                MetricsDaily.date <= today,
                scope(MetricsDaily),
                MetricsDaily.campaign_external_id != "",
            )
            .limit(1)
        )
        is not None
    )


def _moment(day: date, *, tzinfo: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min).replace(tzinfo=tzinfo)


def _period(
    db: Session,
    *,
    owner: User,
    account: Account,
    span: list[Any],
    chosen: Range,
    comparable: bool,
    today: date,
    tzinfo: ZoneInfo,
    currency: str,
    names: dict[str, Any],
    scope: Scope,
    read_until: date | None = None,
) -> Any:
    from app.modules.leads.models import Lead
    from app.modules.leads.selectors import counts_by_campaign

    now = span[-chosen.days :]
    before = span[: chosen.days] if comparable else []
    behind = read_until is not None and read_until < chosen.until
    known = sum(1 for day in now if day.day <= read_until) if behind else None
    facts = facts_by_campaign(
        db,
        owner=owner,
        since=chosen.since,
        until=chosen.until,
        account=account,
        scope=scope,
    )
    leads = counts_by_campaign(
        db,
        owner=owner,
        since=_moment(chosen.since, tzinfo=tzinfo),
        until=_moment(chosen.until + timedelta(days=1), tzinfo=tzinfo),
        scope=scope(Lead),
    )
    earlier = (
        facts_by_campaign(
            db,
            owner=owner,
            since=chosen.since - timedelta(days=chosen.days),
            until=chosen.since - timedelta(days=1),
            account=account,
            scope=scope,
        )
        if comparable
        else {}
    )
    blocks = outcome_blocks.outcomes(
        facts=facts,
        earlier=earlier,
        leads=leads,
        names=names,
        now=total(now),
        before=total(before),
        currency=currency,
    )
    views = _kind_views(
        db,
        owner=owner,
        account=account,
        chosen=chosen,
        tzinfo=tzinfo,
        scope=scope,
        blocks=blocks,
        days=now,
        currency=currency,
        known=known,
        keys=set(facts) | set(earlier) | set(names),
        leads=leads,
        names=names,
    )
    return periods.build(
        key=chosen.key,
        label=range_label(chosen),
        days=now,
        before=before,
        views=views,
        scoped_to=views[0].label if len(views) > 1 else "",
        span=chosen.days,
        in_progress=chosen.until >= today,
        known=known,
        unknown_after=read_until.strftime("%d.%m") if behind and read_until else "",
        currency=currency,
        rows=periods.campaigns(
            facts=facts, leads=leads, names=names, currency=currency
        ),
        blocks=blocks,
        lead_reported=outcome_blocks.lead_reported(
            facts=facts, leads=leads, names=names
        ),
    )


def _kind_views(
    db: Session,
    *,
    owner: User,
    account: Account,
    chosen: Range,
    tzinfo: ZoneInfo,
    scope: Scope,
    blocks: tuple[Any, ...],
    days: list[Any],
    currency: str,
    known: int | None,
    keys: set[str],
    leads: dict[str, tuple[int, int]],
    names: dict[str, Any],
) -> tuple[KindView, ...]:
    active = [
        one for one in blocks if one.spend_minor or (one.count and one.count != "0")
    ]
    if not active:
        return ()
    if len({one.kind for one in blocks}) < 2:
        head = active[0]
        return (
            periods.view(
                kind=head.kind,
                label=head.label,
                days=days,
                currency=currency,
                known=known,
            ),
        )
    return tuple(
        periods.view(
            kind=one.kind,
            label=one.label,
            days=daily_facts(
                db,
                owner=owner,
                since=chosen.since,
                until=chosen.until,
                tzinfo=tzinfo,
                account=account,
                scope=both(
                    scope,
                    campaigns_scope(
                        outcome_blocks.campaigns_of(
                            one.kind, keys=keys, leads=leads, names=names
                        )
                    ),
                ),
            ),
            currency=currency,
            known=known,
        )
        for one in active
    )


def _cuts(
    db: Session,
    *,
    owner: User,
    views: tuple[KindView, ...],
    segments: tuple[SegmentBlock, ...],
    hours: tuple[Any, ...],
    cities: tuple[Any, ...],
    names: dict[str, Any],
    spans: dict[str, int],
    since: date,
    today: date,
    currency: str,
    account: Account,
    scope: Scope,
) -> tuple[KindCuts, ...]:
    kinds = [one.kind for one in views]
    spread = (
        {
            str(cut): segment_spread(
                db,
                owner=owner,
                since=since,
                until=today,
                kind=cut,
                account=account,
                scope=scope,
            )
            for cut in SEGMENT_TITLES
        }
        if any(kind != "lead" for kind in kinds)
        else {}
    )
    return kind_cuts(
        kinds=kinds,
        segments=segments,
        hours=hours,
        cities=cities,
        spread=spread,
        names=names,
        spans=spans,
        currency=currency,
        label_of=slice_label,
    )


def range_label(chosen: Range) -> str:
    if chosen.key == CUSTOM:
        return f"{chosen.since:%d.%m} - {chosen.until:%d.%m}"
    return Period(chosen.key).label


def _recent_leads(
    db: Session, *, owner: User, names: dict[str, Any], scope: Scope
) -> tuple[LeadRow, ...]:
    from app.modules.leads.models import Lead
    from app.modules.leads.selectors import leads_for

    return tuple(
        LeadRow(
            pk=str(lead.id),
            name=lead.full_name or "Ism yozilmagan",
            city=lead.city,
            phone_masked=masked(lead.phone_e164),
            when=localtime(lead.submitted_at).strftime("%d.%m %H:%M"),
            campaign=names[lead.campaign_external_id].name
            if lead.campaign_external_id in names
            else "",
            verdict=getattr(lead, "verdict", "") or "",
        )
        for lead in leads_for(db, owner=owner, scope=scope(Lead), limit=RECENT_LEADS)
    )


def _named_levels() -> dict[str, Any]:
    from app.modules.ads.models import Ad, AdSet, Campaign

    return {
        MetricLevel.CAMPAIGN: Campaign,
        MetricLevel.ADSET: AdSet,
        MetricLevel.AD: Ad,
    }


def _recent_decisions(
    db: Session, *, owner: User, campaign_ids: frozenset[str] | None = None
) -> tuple[Decision, ...]:
    from app.modules.ads.models import Ad, AdSet, Campaign
    from app.modules.audit.constants import ActionType, ActorType
    from app.modules.audit.models import ActionLog

    query = select(ActionLog).where(
        ActionLog.owner_id == owner.id, ActionLog.applied_at.is_not(None)
    )
    if campaign_ids is not None:
        ids = list(campaign_ids)
        groups = (
            select(AdSet.external_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(AdSet.owner_id == owner.id, Campaign.external_id.in_(ids))
        )
        adverts = (
            select(Ad.external_id)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(Ad.owner_id == owner.id, Campaign.external_id.in_(ids))
        )
        query = query.where(
            or_(
                and_(
                    ActionLog.target_level == str(MetricLevel.CAMPAIGN),
                    ActionLog.target_external_id.in_(ids),
                ),
                and_(
                    ActionLog.target_level == str(MetricLevel.ADSET),
                    ActionLog.target_external_id.in_(groups),
                ),
                and_(
                    ActionLog.target_level == str(MetricLevel.AD),
                    ActionLog.target_external_id.in_(adverts),
                ),
            )
        )
    rows = list(
        db.scalars(
            query.options(joinedload(ActionLog.actor))
            .order_by(ActionLog.applied_at.desc())
            .limit(RECENT_DECISIONS)
        )
    )
    wanted: dict[str, set[str]] = {}
    levels = _named_levels()
    for row in rows:
        if row.target_level in levels and row.target_external_id:
            wanted.setdefault(row.target_level, set()).add(row.target_external_id)
    found: dict[tuple[str, str], str] = {}
    for level, ids_wanted in wanted.items():
        model = levels[level]
        for external_id, name in db.execute(
            select(model.external_id, model.name).where(
                model.owner_id == owner.id, model.external_id.in_(ids_wanted)
            )
        ):
            if name:
                found[(level, str(external_id))] = str(name)
    labels = dict(ActionType.choices)
    return tuple(
        Decision(
            when=localtime(row.applied_at).strftime("%d.%m %H:%M"),
            action=labels.get(row.action, row.action),
            target=found.get((row.target_level, row.target_external_id), ""),
            reason=row.reason,
            actor="agent" if row.actor_type == ActorType.AGENT else "user",
        )
        for row in rows
    )


def _segments(
    db: Session,
    *,
    owner: User,
    today: date,
    currency: str,
    account: Account = None,
    scope: Scope = EVERYTHING,
    has_forms: bool = True,
    spans: dict[str, int] | None = None,
) -> tuple[SegmentBlock, ...]:
    since = today - timedelta(days=BREAKDOWN_RETENTION_DAYS - 1)
    return tuple(
        _segment_block(
            kind=str(kind),
            comparison=segment_costs(
                db,
                owner=owner,
                since=since,
                until=today,
                kind=kind,
                account=account,
                scope=scope,
            ),
            currency=currency,
            days=spans[str(kind)]
            if spans is not None
            else _span(
                db,
                owner=owner,
                kind=str(kind),
                today=today,
                since=since,
                account=account,
            ),
            has_forms=has_forms,
        )
        for kind in SEGMENT_TITLES
    )


def _span(
    db: Session,
    *,
    owner: User,
    kind: str,
    today: date,
    since: date,
    account: Account = None,
) -> int:
    oldest = oldest_breakdown_date(db, owner=owner, kind=kind, account=account)
    if oldest is None:
        return 0
    return (today - max(oldest, since)).days + 1


def _compare_of(index: int | None) -> str:
    if not index:
        return ""
    if index == 100:
        return "o'rtacha"
    if index < 100:
        return f"o'rtachadan {100 - index}% arzon"
    return f"o'rtachadan {index - 100}% qimmat"


def _segment_block(
    *,
    kind: str,
    comparison: SegmentComparison,
    currency: str,
    days: int,
    has_forms: bool = True,
) -> SegmentBlock:
    def row(cost: Any) -> SegmentRow:
        return SegmentRow(
            label=slice_label(cost.segment),
            cpl=format_minor(amount_minor=cost.cpl_reported_minor, currency=currency)
            if cost.cpl_reported_minor is not None
            else "—",
            index=cost.cpl_index or 0,
            compare=_compare_of(cost.cpl_index),
            leads=cost.leads_reported,
            spend=format_minor(amount_minor=cost.spend_minor, currency=currency),
            spend_share=cost.spend_share,
        )

    everything = (
        *comparison.ranked,
        *comparison.barren,
        *comparison.weak,
        *comparison.thin,
    )
    return SegmentBlock(
        key=kind,
        title=SEGMENT_TITLES[kind],
        days=days,
        leads=sum(cost.leads_reported for cost in everything),
        min_leads=comparison.min_leads,
        best_leads=max((cost.leads_reported for cost in everything), default=0),
        has_forms=has_forms,
        ranked=tuple(row(cost) for cost in comparison.ranked),
        barren=tuple(row(cost) for cost in comparison.barren[:3]),
    )


def slice_label(value: str) -> str:
    return " · ".join(
        str(SEGMENT_LABELS.get(part, part.replace("_", " ")))
        for part in split_segment(value)
    )
