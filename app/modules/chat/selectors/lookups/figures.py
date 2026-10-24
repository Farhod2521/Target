"""Figures by day, and leads counted any way a question cuts them."""

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import ColumnElement, Select, func, not_, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.lookups.common import (
    figure_sums,
    in_subscription,
    money,
    named,
    names_by_level,
    page_currency,
    refused,
    section,
    window,
)
from app.modules.chat.selectors.scope import lead_window
from app.modules.integrations.models import PageAccount
from app.modules.leads.models import Lead, LeadForm
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from core.chat.lookups import GROUP_ROWS, DailyFigures, LeadCounts

_COLUMNS: Final[dict[str, tuple[str, str]]] = {
    "campaign": (MetricLevel.CAMPAIGN, "campaign_external_id"),
    "adset": (MetricLevel.ADSET, "adset_external_id"),
    "ad": (MetricLevel.AD, "ad_external_id"),
}


def daily_figures(
    db: Session,
    *,
    owner: User,
    arguments: DailyFigures,
    scope: PageScope,
    now: datetime,
) -> str:
    """Day by day, for one object or the current ad account's campaigns."""
    from app.modules.metrics.selectors.lead_sources import other_currency_campaigns

    since, until = window(db, owner=owner, days=arguments.days)
    level = _level_of(db, owner=owner, object_id=arguments.object_id)
    if arguments.object_id and level is None:
        return (
            f"Nothing with id {arguments.object_id} in the subscription. "
            "Use find to look it up by name."
        )
    group = (
        _group_of(db, owner=owner, ad_id=arguments.object_id) if level == "ad" else ""
    )
    if level is not None and not _within(
        scope=scope, level=level, object_id=arguments.object_id, group=group
    ):
        return refused(
            scope=scope,
            kind=level,
            level=level,
            external_id=arguments.object_id,
            parent=group,
        )

    apart: frozenset[str] = frozenset()
    if level is None:
        apart = other_currency_campaigns(
            db,
            owner=owner,
            ids=scope.campaign_ids,
            currency=page_currency(db, owner=owner),
        )
        wanted = [key for key in scope.campaign_ids if key not in apart]
        where = [
            MetricsDaily.level == MetricLevel.CAMPAIGN,
            MetricsDaily.campaign_external_id.in_(wanted),
        ]
        column = "campaign_external_id"
        what = "every campaign in the subscription"
    else:
        metric_level, column = _COLUMNS[level]
        where = [
            MetricsDaily.level == metric_level,
            getattr(MetricsDaily, column) == arguments.object_id,
        ]
        wanted = [arguments.object_id]
        what = f"{level} {arguments.object_id}"

    days = {
        row["date"]: row
        for row in db.execute(
            select(MetricsDaily.date, MetricsDaily.currency, *figure_sums())
            .where(
                MetricsDaily.owner_id == owner.id,
                *where,
                MetricsDaily.date >= since,
                MetricsDaily.date <= until,
            )
            .group_by(MetricsDaily.date, MetricsDaily.currency)
            .order_by(MetricsDaily.date)
        ).mappings()
    }
    leads = _leads_by_day(
        db, owner=owner, column=column, ids=wanted, since=since, until=until
    )
    lines = [
        _day_line(day, figures=days.get(day, {}), leads=leads.get(day, 0))
        for day in sorted(set(days) | set(leads))
    ]
    return "\n".join(
        section(
            f"By day for {what}, {since} to {until} (days with nothing are left out)",
            lines,
            empty="no figures and no leads in this window",
        )
        + _in_other_currency(db, owner=owner, ids=apart, since=since, until=until)
    )


def _in_other_currency(
    db: Session, *, owner: User, ids: frozenset[str], since: date, until: date
) -> list[str]:
    from app.modules.metrics.selectors.lead_sources import other_currency_spend

    return [
        f"- also paid in {code}, not on any line above and never to be "
        f"added to one: {money(amount, code)}"
        for code, amount in other_currency_spend(
            db, owner=owner, ids=ids, since=since, until=until
        )
    ]


def _countable(
    owner: User, start: datetime, end: datetime
) -> list[ColumnElement[bool]]:
    from app.modules.leads.selectors import priced

    return [
        Lead.owner_id == owner.id,
        Lead.is_test.is_(False),
        priced(),
        Lead.submitted_at >= start,
        Lead.submitted_at <= end,
    ]


def _with_page(query: Select[Any]) -> Select[Any]:
    return query.outerjoin(LeadForm, LeadForm.id == Lead.form_id).outerjoin(
        PageAccount, PageAccount.id == LeadForm.page_id
    )


def _count(db: Session, where: list[ColumnElement[bool]]) -> int:
    return db.scalar(_with_page(select(func.count(Lead.id))).where(*where)) or 0


def lead_counts(
    db: Session, *, owner: User, arguments: LeadCounts, scope: PageScope, now: datetime
) -> str:
    """How many leads arrived, grouped the way the question asks."""
    since, until = window(db, owner=owner, days=arguments.days)
    start, end = lead_window(db, owner=owner, since=since, until=until)
    countable = _countable(owner, start, end)
    leads = [*countable, _here(scope)]
    total = _count(db, leads)
    organic = _count(db, [*leads, Lead.is_organic.is_(True)])
    rows = _GROUPINGS[arguments.group_by](db, owner, leads, since, until)
    lines = section(
        f"Leads received by {arguments.group_by.replace('_', ' ')}, {since} to {until}",
        rows[:GROUP_ROWS],
        empty="no leads in this window",
    )
    summary = f"- total: {total}"
    if organic:
        summary += f", of which not from an advert: {organic}"
    lines.insert(1, summary)
    return "\n".join(lines + _left_out(db, countable=countable, scope=scope))


def _here(scope: PageScope) -> ColumnElement[bool]:
    return or_(
        Lead.adset_external_id.in_(list(scope.adset_ids)),
        PageAccount.external_id.in_(list(scope.pages)),
    )


def _left_out(
    db: Session, *, countable: list[ColumnElement[bool]], scope: PageScope
) -> list[str]:
    rest = [*countable, not_(func.coalesce(_here(scope), False))]
    theirs = _count(
        db,
        [
            *rest,
            or_(
                Lead.adset_external_id.in_(list(scope.elsewhere)),
                PageAccount.external_id.in_(list(scope.others)),
            ),
        ],
    )
    outside = _count(db, rest) - theirs
    lines = []
    if theirs:
        lines.append(f"- on other pages of this subscription: {theirs}")
    if outside:
        lines.append(f"- on pages outside the subscription: {outside}")
    return lines


def _within(*, scope: PageScope, level: str, object_id: str, group: str) -> bool:
    if level == "campaign":
        return scope.allows_campaign(object_id)
    if level == "adset":
        return scope.allows_adset(object_id)
    return bool(group) and scope.allows_adset(group)


def _group_of(db: Session, *, owner: User, ad_id: str) -> str:
    group = db.scalar(
        select(AdSet.external_id)
        .join(Ad, Ad.adset_id == AdSet.id)
        .where(Ad.owner_id == owner.id, Ad.external_id == ad_id)
        .limit(1)
    )
    return str(group or "")


def _level_of(db: Session, *, owner: User, object_id: str) -> str | None:
    if not object_id:
        return None
    checks: tuple[tuple[str, Select[Any]], ...] = (
        (
            "campaign",
            select(Campaign.id).where(
                Campaign.owner_id == owner.id,
                in_subscription(Campaign.ad_account_id),
                Campaign.external_id == object_id,
            ),
        ),
        (
            "adset",
            select(AdSet.id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == owner.id,
                in_subscription(Campaign.ad_account_id),
                AdSet.external_id == object_id,
            ),
        ),
        (
            "ad",
            select(Ad.id)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                Ad.owner_id == owner.id,
                in_subscription(Campaign.ad_account_id),
                Ad.external_id == object_id,
            ),
        ),
    )
    for level, query in checks:
        if db.scalar(query.limit(1)) is not None:
            return level
    return None


def _day_line(day: date, *, figures: Mapping[str, Any], leads: int) -> str:
    currency = str(figures.get("currency") or "")
    parts = [
        f"spend {money(int(figures.get('spend') or 0), currency)}",
        f"shown {int(figures.get('shown') or 0)}",
        f"link clicks {int(figures.get('link_clicks') or 0)}",
        f"provider counted leads {int(figures.get('reported') or 0)}",
        f"leads received {leads}",
    ]
    for label, key in (
        ("other results", "results"),
        ("remember it", "recallers"),
        ("profile visits", "profile_visits"),
    ):
        if int(figures.get(key) or 0):
            parts.append(f"{label} {int(figures[key])}")
    return f"- {day}: " + ", ".join(parts)


def _local_day(tzinfo: Any) -> Any:
    return func.date(func.timezone(str(tzinfo), Lead.submitted_at))


def _leads_by_day(
    db: Session, *, owner: User, column: str, ids: list[str], since: date, until: date
) -> dict[date, int]:
    """``{day: enquiries}``, bucketed the way the spend beside it was."""
    if not ids:
        return {}
    start, end = lead_window(db, owner=owner, since=since, until=until)
    day = _local_day(start.tzinfo)
    rows = db.execute(
        select(day, func.count(Lead.id))
        .where(*_countable(owner, start, end), getattr(Lead, column).in_(ids))
        .group_by(day)
        .order_by(day)
    )
    return {found: int(count) for found, count in rows}


def _by_day(
    db: Session, owner: User, leads: list[ColumnElement[bool]], since: date, until: date
) -> list[str]:
    tzinfo = lead_window(db, owner=owner, since=since, until=until)[0].tzinfo
    day = _local_day(tzinfo)
    rows = db.execute(
        _with_page(select(day, func.count(Lead.id)))
        .where(*leads)
        .group_by(day)
        .order_by(day)
    )
    return [f"- {found}: {count}" for found, count in rows]


def _by_object(level: str, column: str) -> Callable[..., list[str]]:
    def grouped(
        db: Session,
        owner: User,
        leads: list[ColumnElement[bool]],
        since: date,
        until: date,
    ) -> list[str]:
        field = getattr(Lead, column)
        count = func.count(Lead.id)
        rows = list(
            db.execute(
                _with_page(select(field, count))
                .where(*leads)
                .group_by(field)
                .order_by(count.desc())
            )
        )
        names = names_by_level(
            db, owner=owner, targets=[(level, str(key)) for key, _n in rows]
        )
        reported = _reported(db, owner=owner, column=column, since=since, until=until)
        return [
            _object_line(
                level,
                str(key),
                name=names.get((level, str(key)), ""),
                count=int(found),
                reported=reported.get(str(key)),
            )
            for key, found in rows
        ]

    return grouped


def _object_line(
    level: str, external_id: str, *, name: str, count: int, reported: int | None
) -> str:
    if not external_id:
        return f"- not from any {level}: {count}"
    line = f"- {named(name, external_id)} (id {external_id}): received {count}"
    if reported is not None and reported != count:
        line += f", the provider counted {reported}"
    return line


def _reported(
    db: Session, *, owner: User, column: str, since: date, until: date
) -> dict[str, int]:
    """The provider's own lead count per object, from the groups' rows."""
    if column == "ad_external_id":
        return {}
    field = getattr(MetricsDaily, column)
    rows = db.execute(
        select(field, func.sum(MetricsDaily.leads_reported))
        .where(
            MetricsDaily.owner_id == owner.id,
            MetricsDaily.level == MetricLevel.ADSET,
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
        )
        .group_by(field)
    )
    return {str(key): int(total or 0) for key, total in rows}


def _by_form(
    db: Session, owner: User, leads: list[ColumnElement[bool]], since: date, until: date
) -> list[str]:
    count = func.count(Lead.id)
    rows = db.execute(
        _with_page(select(LeadForm.external_id, LeadForm.name, PageAccount.name, count))
        .where(*leads, PageAccount.is_active.is_(True))
        .group_by(LeadForm.external_id, LeadForm.name, PageAccount.name)
        .order_by(count.desc())
    )
    return [
        f"- form {named(form_name or '', form_id or '?')} "
        f"on page {named(page_name or '', '?')}: {found}"
        for form_id, form_name, page_name, found in rows
    ] + _elsewhere(db, leads)


def _by_page(
    db: Session, owner: User, leads: list[ColumnElement[bool]], since: date, until: date
) -> list[str]:
    count = func.count(Lead.id)
    rows = db.execute(
        _with_page(select(PageAccount.external_id, PageAccount.name, count))
        .where(*leads, PageAccount.is_active.is_(True))
        .group_by(PageAccount.external_id, PageAccount.name)
        .order_by(count.desc())
    )
    return [
        f"- page {named(page_name or '', '?')} (id {page_id}): {found}"
        for page_id, page_name, found in rows
    ] + _elsewhere(db, leads)


def _elsewhere(db: Session, leads: list[ColumnElement[bool]]) -> list[str]:
    unpaid = _count(
        db, [*leads, PageAccount.id.is_not(None), PageAccount.is_active.is_not(True)]
    )
    unknown = _count(db, [*leads, PageAccount.id.is_(None)])
    lines = []
    if unpaid:
        lines.append(f"- on pages outside the subscription: {unpaid}")
    if unknown:
        lines.append(f"- no page recorded: {unknown}")
    return lines


_GROUPINGS: Final[dict[str, Callable[..., list[str]]]] = {
    "day": _by_day,
    "campaign": _by_object("campaign", "campaign_external_id"),
    "ad_group": _by_object("adset", "adset_external_id"),
    "form": _by_form,
    "page": _by_page,
}

__all__ = ["daily_figures", "lead_counts"]
