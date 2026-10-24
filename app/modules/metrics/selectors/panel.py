"""Figures beside one campaign: its chips on the list, its ads' chips, its days."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from adskit import MinorUnits
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import NOT_RUNNING
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel, Period, Ranking
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.ranges import Range
from app.modules.metrics.selectors.campaigns import adsets_kind, campaign_kind
from app.modules.metrics.selectors.card_kinds import RESULT_KEYS, text_of
from app.modules.metrics.selectors.cards import NO_ANSWER
from app.modules.metrics.selectors.facts import cabinet_where, with_people_counts
from app.modules.metrics.selectors.results import UNCOUNTED_LABEL, words_for
from app.modules.metrics.selectors.shapes import AdChips, Chip, ChipRow
from core.metrics import BY_KEY, ROW_KEYS, Outcome, PanelTotals, with_provider_leads

M = MetricsDaily
SUMS: Final[dict[str, Any]] = {
    "spend": M.spend_minor,
    "results": M.results_reported,
    "impressions": M.impressions,
    "link_clicks": M.inline_link_clicks,
    "recallers": M.recallers,
    "profile_visits": M.profile_visits,
    "leads_reported": M.leads_reported,
}
ROW_LABELS: Final[dict[str, str]] = {
    "cpl": "Murojaat narxi",
    "leads": "Murojaatlar",
    "spend": "Sarflandi",
    "reach": "Qamrov",
    "impressions": "Ko'rsatildi",
}
COUNT_KEY: Final = "leads"
RECEIVED_NOTE: Final = "tushdi: %(count)s"
IDLE_NOTES: Final[dict[str, str]] = {
    Period.TODAY: "Bugun sarf yo'q",
    Period.SEVEN: "7 kunda sarf yo'q",
    Period.THIRTY: "30 kunda sarf yo'q",
    Period.NINETY: "90 kunda sarf yo'q",
}
IDLE_NOTE_CUSTOM: Final = "Bu kunlarda sarf yo'q"


def start_of(day: date, tzinfo: Any) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tzinfo)


def end_of(day: date, tzinfo: Any) -> datetime:
    return datetime.combine(day, time.max, tzinfo=tzinfo)


def _summed(
    db: Session, key: Any, *, owner: User, level: str, where: list[Any]
) -> dict[str, dict[str, int]]:
    rows = db.execute(
        select(
            key,
            *[
                func.coalesce(func.sum(col), 0).label(name)
                for name, col in SUMS.items()
            ],
        )
        .where(
            *cabinet_where(db, owner=owner, level=level, account=EVERY_ACCOUNT), *where
        )
        .group_by(key)
    )
    return {row[0]: {name: int(row._mapping[name]) for name in SUMS} for row in rows}


def totals_of(*, sums: dict[str, int], leads: tuple[int, int] | int) -> PanelTotals:
    count, qualified = leads if isinstance(leads, tuple) else (leads, 0)
    return PanelTotals(
        spend_minor=MinorUnits(sums.get("spend", 0)),
        leads=count,
        qualified=qualified,
        results=sums.get("results", 0),
        impressions=sums.get("impressions", 0),
        link_clicks=sums.get("link_clicks", 0),
        recallers=sums.get("recallers", 0),
        profile_visits=sums.get("profile_visits", 0),
        leads_reported=sums.get("leads_reported", 0),
        reach=sums.get("reach", 0),
    )


def chips_for(
    *, totals: PanelTotals, currency: str, kind: Outcome = "lead"
) -> tuple[Chip, ...]:
    shown = with_provider_leads(totals) if kind == "lead" else totals
    return tuple(
        _chip(key, totals=shown, currency=currency, kind=kind) for key in ROW_KEYS
    )


def _chip(key: str, *, totals: PanelTotals, currency: str, kind: Outcome) -> Chip:
    if key in RESULT_KEYS and not words_for(kind).field:
        return Chip(key=key, label=str(UNCOUNTED_LABEL), display=NO_ANSWER)
    short = ROW_LABELS.get(key) if kind == "lead" or key not in RESULT_KEYS else None
    source = ""
    if key == COUNT_KEY:
        if kind == "lead":
            source = (
                ""
                if totals.received == totals.leads
                else RECEIVED_NOTE % {"count": totals.received}
            )
        else:
            source = str(words_for(kind).source_note)
    return Chip(
        key=key,
        label=str(short or text_of(BY_KEY[key], kind=kind).label),
        display=text_of(BY_KEY[key], kind=kind).display(totals, None, currency)
        or NO_ANSWER,
        source=source,
    )


def _quiet(row: Any, *, spent: int, date_range: Range) -> str:
    if spent or str(row.delivery) not in NOT_RUNNING:
        return ""
    return IDLE_NOTES.get(date_range.key, IDLE_NOTE_CUSTOM)


def campaign_chips(
    db: Session,
    *,
    owner: User,
    campaigns: list[Any],
    date_range: Range,
    account: AdAccount | None = None,
) -> tuple[ChipRow, ...]:
    from app.modules.integrations.selectors import active_ad_account
    from app.modules.leads.selectors import counts_by_campaign

    if not campaigns:
        return ()
    account = account if account is not None else active_ad_account(db, owner=owner)
    tzinfo = account.tzinfo() if account else ZoneInfo("UTC")
    since, until = date_range.since, date_range.until
    sums = _summed(
        db,
        M.campaign_external_id,
        owner=owner,
        level=MetricLevel.ADSET,
        where=[
            M.date >= since,
            M.date <= until,
            M.campaign_external_id.in_([str(c.external_id) for c in campaigns]),
        ],
    )
    spend = with_people_counts(
        db, sums, owner=owner, level=MetricLevel.CAMPAIGN, since=since, until=until
    )
    leads = counts_by_campaign(
        db, owner=owner, since=start_of(since, tzinfo), until=end_of(until, tzinfo)
    )
    return tuple(
        ChipRow(
            campaign_id=str(campaign.id),
            chips=chips_for(
                totals=totals_of(
                    sums=spend.get(campaign.external_id, {}),
                    leads=leads.get(campaign.external_id, (0, 0)),
                ),
                currency=campaign.ad_account.currency,
                kind=adsets_kind(campaign.adsets),
            ),
            quiet=_quiet(
                campaign,
                spent=spend.get(campaign.external_id, {}).get("spend", 0),
                date_range=date_range,
            ),
        )
        for campaign in campaigns
    )


def group_chips(
    db: Session, *, owner: User, adsets: list[Any], date_range: Range, tzinfo: ZoneInfo
) -> tuple[ChipRow, ...]:
    from app.modules.leads.selectors import counts_by_adset

    if not adsets:
        return ()
    since, until = date_range.since, date_range.until
    sums = _summed(
        db,
        M.adset_external_id,
        owner=owner,
        level=MetricLevel.ADSET,
        where=[
            M.date >= since,
            M.date <= until,
            M.adset_external_id.in_([str(a.external_id) for a in adsets]),
        ],
    )
    spend = with_people_counts(
        db, sums, owner=owner, level=MetricLevel.ADSET, since=since, until=until
    )
    leads = counts_by_adset(
        db, owner=owner, since=start_of(since, tzinfo), until=end_of(until, tzinfo)
    )
    return tuple(
        ChipRow(
            campaign_id=str(adset.external_id),
            chips=chips_for(
                totals=totals_of(
                    sums=spend.get(adset.external_id, {}),
                    leads=leads.get(adset.external_id, (0, 0)),
                ),
                currency=adset.campaign.ad_account.currency,
                kind=adsets_kind([adset]),
            ),
            quiet=_quiet(
                adset,
                spent=spend.get(adset.external_id, {}).get("spend", 0),
                date_range=date_range,
            ),
        )
        for adset in adsets
    )


def ad_chips(
    db: Session, *, owner: User, campaign: Any, date_range: Range
) -> tuple[AdChips, ...]:
    from app.modules.leads.selectors import tallies_by_ad

    account = campaign.ad_account
    tzinfo = account.tzinfo()
    since, until = date_range.since, date_range.until
    sums = _summed(
        db,
        M.external_id,
        owner=owner,
        level=MetricLevel.AD,
        where=[
            M.provider == campaign.provider,
            M.campaign_external_id == campaign.external_id,
            M.date >= since,
            M.date <= until,
            M.external_id != "",
        ],
    )
    if not sums:
        return ()
    sums = with_people_counts(
        db, sums, owner=owner, level=MetricLevel.AD, since=since, until=until
    )
    kind = campaign_kind(db, owner=owner, campaign=campaign)
    leads: dict[str, int] = {}
    if kind == "lead":
        tallies = tallies_by_ad(
            db,
            owner=owner,
            since=start_of(since, tzinfo),
            until=start_of(until + timedelta(days=1), tzinfo),
        )
        leads = {t.external_id: t.leads for t in tallies if t.external_id in sums}
    return tuple(
        AdChips(
            ad_id=ad_id,
            chips=chips_for(
                totals=totals_of(sums=row, leads=leads.get(ad_id, 0)),
                currency=account.currency,
                kind=kind,
            ),
        )
        for ad_id, row in sums.items()
    )


def spend_total(
    db: Session, *, owner: User, campaigns: list[Any], date_range: Range, currency: str
) -> int:
    ids = {str(c.external_id) for c in campaigns if c.ad_account.currency == currency}
    if not ids:
        return 0
    total = db.scalar(
        select(func.sum(M.spend_minor)).where(
            *cabinet_where(
                db, owner=owner, level=MetricLevel.ADSET, account=EVERY_ACCOUNT
            ),
            M.date >= date_range.since,
            M.date <= date_range.until,
            M.campaign_external_id.in_(ids),
        )
    )
    return int(total or 0)


# -- every day of one campaign -----------------------------------------------------------

_SUMMED: Final[dict[str, Any]] = {
    "spend_minor": M.spend_minor,
    "impressions": M.impressions,
    "clicks": M.clicks,
    "link_clicks": M.inline_link_clicks,
    "landing_page_views": M.landing_page_views,
    "leads_reported": M.leads_reported,
    "results_reported": M.results_reported,
    "video_plays": M.video_plays,
    "video_thruplays": M.video_thruplays,
    "reactions": M.reactions,
    "comments": M.comments,
    "shares": M.shares,
    "saves": M.saves,
}


@dataclass(frozen=True, slots=True)
class FigureSums:
    spend_minor: int = 0
    impressions: int = 0
    clicks: int = 0
    link_clicks: int = 0
    landing_page_views: int = 0
    leads_reported: int = 0
    results_reported: int = 0
    video_plays: int = 0
    video_thruplays: int = 0
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0

    @property
    def ctr_percent(self) -> str:
        if not self.impressions:
            return ""
        return f"{self.clicks * 100 / self.impressions:.2f}"

    @property
    def cpm_minor(self) -> int | None:
        if not self.impressions:
            return None
        return self.spend_minor * 1000 // self.impressions

    def plus(self, other: "FigureSums") -> "FigureSums":
        return FigureSums(
            **{name: getattr(self, name) + getattr(other, name) for name in _SUMMED}
        )


@dataclass(frozen=True, slots=True)
class FigureDay:
    day: date
    sums: FigureSums
    reach: int


@dataclass(frozen=True, slots=True)
class AdFigures:
    external_id: str
    name: str
    sums: FigureSums
    quality_ranking: str


@dataclass(frozen=True, slots=True)
class CampaignFigures:
    currency: str
    total: FigureSums
    widest_reach: int
    days: tuple[FigureDay, ...]
    ads: tuple[AdFigures, ...]
    synced_at: datetime | None
    groups: tuple[AdFigures, ...] = ()


def _sum_columns() -> list[Any]:
    return [
        func.coalesce(func.sum(col), 0).label(name) for name, col in _SUMMED.items()
    ]


def _figures(row: Any) -> FigureSums:
    return FigureSums(**{name: int(row._mapping[name] or 0) for name in _SUMMED})


def _days(
    db: Session, *, owner: User, provider: str, level: str, key: str
) -> list[Any]:
    where = (
        M.external_id == key
        if level == MetricLevel.CAMPAIGN
        else M.campaign_external_id == key
    )
    return list(
        db.execute(
            select(
                M.date,
                *_sum_columns(),
                func.max(M.reach).label("reach"),
                func.max(M.currency).label("currency"),
                func.max(M.synced_at).label("synced"),
            )
            .where(
                M.owner_id == owner.id,
                M.provider == provider,
                M.level == str(level),
                where,
            )
            .group_by(M.date)
            .order_by(M.date.desc())
        )
    )


def _ads(
    db: Session, *, owner: User, provider: str, level: str, campaign: str
) -> tuple[AdFigures, ...]:
    where = (
        M.owner_id == owner.id,
        M.provider == provider,
        M.level == str(level),
        M.campaign_external_id == campaign,
    )
    spend = func.coalesce(func.sum(M.spend_minor), 0)
    grouped = db.execute(
        select(M.external_id, *_sum_columns(), func.max(M.object_name).label("name"))
        .where(*where)
        .group_by(M.external_id)
        .order_by(spend.desc(), M.external_id)
    )
    newest = dict(
        db.execute(
            select(M.external_id, M.quality_ranking)
            .where(*where, M.quality_ranking != "")
            .order_by(M.external_id, M.date.desc())
            .distinct(M.external_id)
        ).all()
    )
    labels = dict(Ranking.choices)
    return tuple(
        AdFigures(
            external_id=row.external_id,
            name=row.name or "",
            sums=_figures(row),
            quality_ranking=str(labels.get(newest.get(row.external_id, ""), "")),
        )
        for row in grouped
    )


def campaign_figures(
    db: Session,
    *,
    owner: User,
    provider: str,
    campaign_external_id: str,
    fall_back: bool = False,
) -> CampaignFigures:
    day_rows = _days(
        db,
        owner=owner,
        provider=provider,
        level=MetricLevel.CAMPAIGN,
        key=campaign_external_id,
    )
    if not day_rows and fall_back:
        day_rows = _days(
            db,
            owner=owner,
            provider=provider,
            level=MetricLevel.ADSET,
            key=campaign_external_id,
        )
    days = tuple(
        FigureDay(day=row.date, sums=_figures(row), reach=int(row.reach or 0))
        for row in day_rows
    )
    total = FigureSums()
    for day in days:
        total = total.plus(day.sums)
    return CampaignFigures(
        currency=day_rows[0].currency if day_rows else "",
        total=total,
        widest_reach=max((day.reach for day in days), default=0),
        days=days,
        ads=_ads(
            db,
            owner=owner,
            provider=provider,
            level=MetricLevel.AD,
            campaign=campaign_external_id,
        ),
        synced_at=max((row.synced for row in day_rows if row.synced), default=None),
        groups=_ads(
            db,
            owner=owner,
            provider=provider,
            level=MetricLevel.ADSET,
            campaign=campaign_external_id,
        ),
    )
