"""Every delivering group's last three days against its usual price (TZ 1).

The figures come from the stored daily rows of each advert: the window's
three finished days, and the 90 days before them for the usual price
(TZ 1.2). Frequency is people counted once over a range - the provider's
seven-day and 90-day counts - never a sum of days.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import business_for
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily, PeopleCount
from app.modules.metrics.selectors.facts import cabinet_where
from core.agent.price_rise import (
    HISTORY_DAYS,
    WINDOW_DAYS,
    Figures,
    Source,
    Usual,
    usual_of,
)
from core.metrics import formulas, outcome_for
from core.metrics.outcomes import SITE_GOAL, is_custom_conversion, site_event

# TZ 1.3: the exceptions.
YOUNG: Final = timedelta(hours=48)
EDITED: Final = timedelta(hours=72)
# Changes that do not touch what an advert shows or to whom.
NOT_EDITS: Final = frozenset({ActionType.NAME_SET})
# What one result is, for the kinds whose price means anything.
PRICED: Final = frozenset({"lead", "chat", "call", "click", "profile", "site_lead"})
CHAT_KINDS: Final = frozenset({"chat"})
WEEK_SPAN: Final = 6
HISTORY_SPAN: Final = 89

_SUMMED: Final = (
    ("spend_minor", MetricsDaily.spend_minor),
    ("impressions", MetricsDaily.impressions),
    ("results", MetricsDaily.results_reported),
    ("link_clicks", MetricsDaily.inline_link_clicks),
    ("clicks", MetricsDaily.clicks),
    ("views_3s", MetricsDaily.video_views_3s),
    ("thruplays", MetricsDaily.video_thruplays),
)
_RANKINGS: Final = (
    ("quality", MetricsDaily.quality_ranking),
    ("engagement", MetricsDaily.engagement_rate_ranking),
    ("conversion", MetricsDaily.conversion_rate_ranking),
)


def result_key(goal: str, promoted: Mapping[str, object] | None) -> str:
    """TZ 1.2 and 3.3: what one result is - a website result by its event -
    or ``""`` for a goal whose price says nothing (reach, recall)."""
    if goal.strip().upper() == SITE_GOAL:
        if is_custom_conversion(promoted):
            return f"site:cc:{(promoted or {}).get('custom_conversion_id')}"
        event = site_event(promoted)
        return f"site:{event}" if event else ""
    kind = outcome_for(goal, promoted) if goal.strip() else "lead"
    return kind if kind in PRICED else ""


@dataclass(frozen=True, slots=True)
class Advert:
    """One advert's window and the history it brings to the usual price."""

    ad_id: str
    name: str
    now: Figures
    history: Figures
    live: bool
    first_spent: date | None
    # TZ 1.3: refused, unpaid or flagged by the provider - its own notice first.
    troubled: bool = False


@dataclass(frozen=True, slots=True)
class Judged:
    """One delivering group, ready to be held against its usual price.

    ``usual`` is ``None`` when neither the account nor the niche has one;
    ``excepted`` names the TZ 1.3 exception that keeps it quiet.
    """

    account: AdAccount
    adset_id: str
    campaign_pk: str
    name: str
    key: str
    now: Figures
    adverts: list[Advert]
    usual: Usual | None
    excepted: str = ""


def judged_groups(db: Session, *, owner: User, now: datetime) -> list[Judged]:
    """Every delivering group of the owner's connected accounts."""
    from app.modules.integrations.selectors.slots import enabled_ad_accounts

    niche = _Niche(db, owner=owner)
    found: list[Judged] = []
    for account in enabled_ad_accounts(db, owner=owner):
        found += _account(db, owner=owner, account=account, now=now, niche=niche)
    return found


def usual_prices(db: Session, *, owner: User, now: datetime) -> dict[str, int]:
    """``{group: its usual price}`` - the one TZ 6.4's «odatda» quotes too."""
    return {
        item.adset_id: round(item.usual.cost)
        for item in judged_groups(db, owner=owner, now=now)
        if item.usual is not None
    }


def window_of(account: AdAccount, now: datetime) -> tuple[date, date]:
    """The last three finished days in the account's own clock."""
    today = now.astimezone(account.tzinfo()).date()
    return today - timedelta(days=WINDOW_DAYS), today - timedelta(days=1)


def _account(
    db: Session, *, owner: User, account: AdAccount, now: datetime, niche: "_Niche"
) -> list[Judged]:
    since, until = window_of(account, now)
    start = since - timedelta(days=HISTORY_DAYS)
    groups = list(
        db.scalars(
            select(AdSet)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(AdSet.owner_id == owner.id, Campaign.ad_account_id == account.id)
        )
    )
    if not groups:
        return []
    keys = {
        group.external_id: result_key(
            group.optimization_goal_raw or "", group.promoted_object_raw
        )
        for group in groups
    }
    rows = _ad_rows(
        db, owner=owner, account=account, start=start, since=since, until=until
    )
    adverts = _adverts(db, owner=owner, account=account, rows=rows, until=until)
    by_group: dict[str, list[Advert]] = defaultdict(list)
    for adset_id, advert in adverts:
        by_group[adset_id].append(advert)
    edited = _edited(db, owner=owner, groups=groups, now=now)
    week = _people(
        db, owner=owner, account=account, level=MetricLevel.ADSET, span=WEEK_SPAN
    )
    found: list[Judged] = []
    for group in groups:
        key = keys[group.external_id]
        own = by_group.get(group.external_id, [])
        current = _sum(advert.now for advert in own)
        if not key or group.delivery != Delivery.ACTIVE or not current.spend_minor:
            continue
        others = [
            advert.history
            for adset_id, advert in adverts
            if keys.get(adset_id) == key and adset_id != group.external_id
        ]
        usual = usual_of(others, source="account_history") or niche.usual(
            key=key,
            currency=account.currency,
            start=start,
            until=since - timedelta(days=1),
        )
        found.append(
            Judged(
                account=account,
                adset_id=group.external_id,
                campaign_pk=str(group.campaign_id),
                name=group.name,
                key=key,
                now=_with_frequency(
                    replace(current, chat=key in CHAT_KINDS),
                    week.get(group.external_id),
                ),
                adverts=[
                    replace(a, now=replace(a.now, chat=key in CHAT_KINDS)) for a in own
                ],
                usual=usual,
                excepted=_excepted(group, own=own, edited=edited, now=now, until=until),
            )
        )
    return found


def _excepted(
    group: AdSet, *, own: list[Advert], edited: set[str], now: datetime, until: date
) -> str:
    """TZ 1.3: why the group is not judged tonight, or ``""``."""
    campaign = group.campaign
    troubled = (
        group.issue_codes
        or (campaign is not None and campaign.issue_codes)
        or any(advert.troubled for advert in own if advert.now.spend_minor)
    )
    if troubled:
        return "delivery"
    first = min((a.first_spent for a in own if a.first_spent), default=None)
    young_start = group.start_time is not None and group.start_time > now - YOUNG
    if young_start or first is None or first > until - timedelta(days=1):
        return "young"
    ids = {group.external_id, *(a.ad_id for a in own)}
    if campaign is not None:
        ids.add(campaign.external_id)
    if ids & edited:
        return "edited"
    return ""


def _ad_rows(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    start: date,
    since: date,
    until: date,
) -> list[Any]:
    m = MetricsDaily
    window = m.date >= since
    columns = [
        func.sum(column).filter(window).label(f"now_{name}") for name, column in _SUMMED
    ] + [
        func.sum(column).filter(~window).label(f"was_{name}")
        for name, column in _SUMMED
    ]
    return list(
        db.execute(
            select(
                m.adset_external_id,
                m.ad_external_id,
                func.max(m.object_name).label("name"),
                func.min(m.date).filter(m.spend_minor > 0).label("first_spent"),
                *columns,
            )
            .where(
                *cabinet_where(db, owner=owner, level=MetricLevel.AD, account=account),
                m.date >= start,
                m.date <= until,
            )
            .group_by(m.adset_external_id, m.ad_external_id)
        )
    )


def _made(get: Callable[[str], Any], *, chat: bool = False) -> Figures:
    """Figures from summed columns, read by their names."""
    return Figures(
        spend_minor=int(get("spend_minor") or 0),
        impressions=int(get("impressions") or 0),
        results=int(get("results") or 0),
        link_clicks=int(get("link_clicks") or 0),
        clicks=int(get("clicks") or 0),
        views_3s=int(get("views_3s") or 0),
        thruplays=int(get("thruplays") or 0),
        chat=chat,
    )


def _troubled(delivery: str, flagged: bool) -> bool:
    return flagged or delivery in (Delivery.REJECTED, Delivery.BILLING)


def _figures(row: Any, prefix: str) -> Figures:
    return _made(lambda name: getattr(row, f"{prefix}_{name}"))


def _adverts(
    db: Session, *, owner: User, account: AdAccount, rows: list[Any], until: date
) -> list[tuple[str, Advert]]:
    ids = [row.ad_external_id for row in rows]
    mirrored = {
        ad_id: (delivery, bool(codes))
        for ad_id, delivery, codes in db.execute(
            select(Ad.external_id, Ad.delivery, Ad.issue_codes).where(
                Ad.owner_id == owner.id, Ad.external_id.in_(ids)
            )
        )
    }
    rankings = _rankings(db, owner=owner, account=account, ids=ids, until=until)
    week = _people(
        db, owner=owner, account=account, level=MetricLevel.AD, span=WEEK_SPAN
    )
    whole = _people(
        db, owner=owner, account=account, level=MetricLevel.AD, span=HISTORY_SPAN
    )
    found: list[tuple[str, Advert]] = []
    for row in rows:
        ad_id = row.ad_external_id
        now = _with_frequency(
            replace(_figures(row, "now"), rankings=rankings.get(ad_id, {})),
            week.get(ad_id),
        )
        history = _with_frequency(_figures(row, "was"), whole.get(ad_id))
        found.append(
            (
                row.adset_external_id,
                Advert(
                    ad_id=ad_id,
                    name=row.name or "",
                    now=now,
                    history=history,
                    live=mirrored.get(ad_id, ("", False))[0] == Delivery.ACTIVE,
                    troubled=_troubled(*mirrored.get(ad_id, ("", False))),
                    first_spent=row.first_spent,
                ),
            )
        )
    return found


def _with_frequency(figures: Figures, counted: "Counted | None") -> Figures:
    """People scaled to the figures' showings, so the frequency is the one of
    the range they were counted over and nothing else moves."""
    if counted is None or not counted.reach or not counted.shown:
        return replace(figures, reach=0)
    return replace(
        figures,
        reach=max(1, round(counted.reach * figures.impressions / counted.shown)),
    )


@dataclass(frozen=True, slots=True)
class Counted:
    """People counted once over a range, and the showings of that range."""

    reach: int
    shown: int


def _people(
    db: Session, *, owner: User, account: AdAccount, level: str, span: int
) -> dict[str, Counted]:
    """``{object: its people}`` over the newest stored range of ``span + 1`` days."""
    newest: dict[str, tuple[int, date, date]] = {}
    for external_id, reach, since, until in db.execute(
        select(
            PeopleCount.external_id,
            PeopleCount.reach,
            PeopleCount.since,
            PeopleCount.until,
        )
        .where(
            PeopleCount.owner_id == owner.id,
            PeopleCount.ad_account_id == account.id,
            PeopleCount.level == str(level),
            PeopleCount.until - PeopleCount.since == span,
        )
        .order_by(PeopleCount.until.desc())
    ):
        newest.setdefault(external_id, (int(reach or 0), since, until))
    ranges: dict[tuple[date, date], list[str]] = defaultdict(list)
    for external_id, (_reach, since, until) in newest.items():
        ranges[(since, until)].append(external_id)
    m = MetricsDaily
    column = m.ad_external_id if level == MetricLevel.AD else m.adset_external_id
    shown: dict[str, int] = {}
    for (since, until), ids in ranges.items():
        for external_id, total in db.execute(
            select(column, func.sum(m.impressions))
            .where(
                *cabinet_where(db, owner=owner, level=level, account=account),
                column.in_(ids),
                m.date >= since,
                m.date <= until,
            )
            .group_by(column)
        ):
            shown[external_id] = int(total or 0)
    return {
        external_id: Counted(reach=reach, shown=shown.get(external_id, 0))
        for external_id, (reach, _since, _until) in newest.items()
    }


def _rankings(
    db: Session, *, owner: User, account: AdAccount, ids: list[str], until: date
) -> dict[str, dict[str, str]]:
    """Each advert's newest known rankings in the window."""
    m = MetricsDaily
    since = until - timedelta(days=WINDOW_DAYS - 1)
    found: dict[str, dict[str, str]] = defaultdict(dict)
    rows = db.execute(
        select(m.ad_external_id, *(column for _n, column in _RANKINGS))
        .where(
            *cabinet_where(db, owner=owner, level=MetricLevel.AD, account=account),
            m.ad_external_id.in_(ids),
            m.date >= since,
            m.date <= until,
        )
        .order_by(m.date.desc())
    )
    for row in rows:
        for index, (name, _column) in enumerate(_RANKINGS, start=1):
            value = (row[index] or "").lower()
            if value and value != "unknown":
                found[row[0]].setdefault(name, value)
    return found


def _edited(
    db: Session, *, owner: User, groups: list[AdSet], now: datetime
) -> set[str]:
    """TZ 1.3: what was changed here, or got a new advert, in the last 72 hours."""
    since = now - EDITED
    found = set(
        db.scalars(
            select(ActionLog.target_external_id).where(
                ActionLog.owner_id == owner.id,
                ActionLog.status == ActionStatus.APPLIED,
                ActionLog.dry_run.is_(False),
                ActionLog.action.not_in(list(NOT_EDITS)),
                ActionLog.created_at >= since,
            )
        )
    )
    found |= set(
        db.scalars(
            select(AdSet.external_id)
            .join(Ad, Ad.adset_id == AdSet.id)
            .where(
                AdSet.id.in_([group.id for group in groups]),
                Ad.created_at >= since,
            )
        )
    )
    return found


def _sum(items: Iterable[Figures]) -> Figures:
    totals: dict[str, int] = defaultdict(int)
    for item in items:
        for name, _c in _SUMMED:
            totals[name] += getattr(item, name)
    return _made(totals.get)


class _Niche:
    """TZ 1.2: the niche's usual price - other accounts of the same
    direction, the same result, the same currency. Read once a night."""

    def __init__(self, db: Session, *, owner: User) -> None:
        self.db = db
        self.owner = owner
        business = business_for(db, owner)
        self.direction = business.direction_id if business is not None else None
        self.cache: dict[tuple[str, str, date, date], Usual | None] = {}

    def usual(
        self, *, key: str, currency: str, start: date, until: date
    ) -> Usual | None:
        if self.direction is None:
            return None
        wanted = (key, currency, start, until)
        if wanted not in self.cache:
            self.cache[wanted] = self._read(
                key=key, currency=currency, start=start, until=until
            )
        return self.cache[wanted]

    def _read(
        self, *, key: str, currency: str, start: date, until: date
    ) -> Usual | None:
        m = MetricsDaily
        owners = select(Business.user_id).where(
            Business.direction_id == self.direction, Business.user_id != self.owner.id
        )
        accounts = select(AdAccount.id).where(
            AdAccount.owner_id.in_(owners), AdAccount.currency == currency
        )
        rows = self.db.execute(
            select(
                m.ad_external_id,
                AdSet.optimization_goal_raw,
                AdSet.promoted_object_raw,
                *(func.sum(column).label(name) for name, column in _SUMMED),
            )
            .join(
                AdSet,
                (AdSet.external_id == m.adset_external_id)
                & (AdSet.owner_id == m.owner_id),
            )
            .where(
                m.level == MetricLevel.AD,
                m.ad_account_id.in_(accounts),
                m.date >= start,
                m.date <= until,
            )
            .group_by(
                m.ad_external_id, AdSet.optimization_goal_raw, AdSet.promoted_object_raw
            )
        )
        source: Source = "niche_average"
        return usual_of(
            (
                _made(partial(getattr, row), chat=key in CHAT_KINDS)
                for row in rows
                if result_key(row.optimization_goal_raw or "", row.promoted_object_raw)
                == key
            ),
            source=source,
        )


def cost_after(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    adset_id: str,
    since: date,
    until: date,
) -> int | None:
    """TZ 1.7: what one result cost the group between two days, or nothing."""
    m = MetricsDaily
    spent, results = db.execute(
        select(func.sum(m.spend_minor), func.sum(m.results_reported)).where(
            *cabinet_where(db, owner=owner, level=MetricLevel.AD, account=account),
            m.adset_external_id == adset_id,
            m.date >= since,
            m.date <= until,
        )
    ).one()
    return formulas.cost_per_result(int(spent or 0), int(results or 0))


__all__ = [
    "Advert",
    "Judged",
    "cost_after",
    "judged_groups",
    "result_key",
    "usual_prices",
    "window_of",
]
