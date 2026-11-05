"""The nightly check against Ads Manager.

Meta's own account total for each closed day, read again the night after,
beside the sum of the ad set rows we stored for it. The two are the same
numbers when nothing was lost: a day apart is a page we never stored, a
campaign we dropped or a day Meta restated after we read it.

Only what an account total and a sum of ad sets mean alike is compared.
Leads are not: an ad set counts the result of its own goal, the account
every lead of every kind.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from adskit.dto import MetricsDTO
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import CHECK_DAYS, CHECK_TOLERANCE_PCT, MetricLevel
from app.modules.metrics.models import MetricsCheck, MetricsDaily

logger = logging.getLogger(__name__)
M = MetricsDaily
CHECKED_PROVIDER: Final = "meta"
ACCOUNT_LEVEL: Final = "account"
# Each compared figure: its stored column, and its field on Meta's row.
CHECKED: Final[dict[str, tuple[Any, str]]] = {
    "spend_minor": (M.spend_minor, "spend_minor"),
    "impressions": (M.impressions, "impressions"),
    "clicks": (M.clicks, "clicks"),
    "link_clicks": (M.inline_link_clicks, "inline_link_clicks"),
    "purchases_site": (M.purchases_site, "purchases_site"),
}


@dataclass(frozen=True, slots=True)
class CheckSummary:
    days: int = 0
    differing: tuple[date, ...] = ()


def check_range(today: date) -> tuple[date, date]:
    """The closed days: today is still being spent."""
    return today - timedelta(days=CHECK_DAYS), today - timedelta(days=1)


def stored_days(
    db: Session, *, ad_account: AdAccount, since: date, until: date
) -> dict[date, dict[str, int]]:
    rows = db.execute(
        select(
            M.date,
            *[
                func.coalesce(func.sum(column), 0).label(name)
                for name, (column, _) in CHECKED.items()
            ],
        )
        .where(
            M.ad_account_id == ad_account.id,
            M.level == str(MetricLevel.ADSET),
            M.date >= since,
            M.date <= until,
        )
        .group_by(M.date)
    )
    return {row[0]: {name: int(row._mapping[name]) for name in CHECKED} for row in rows}


def network_days(rows: list[MetricsDTO]) -> dict[date, dict[str, int]]:
    found: dict[date, dict[str, int]] = {}
    for row in rows:
        day = found.setdefault(row.day, dict.fromkeys(CHECKED, 0))
        for name, (_, field) in CHECKED.items():
            day[name] += int(getattr(row, field) or 0)
    return found


def apart(ours: int, theirs: int) -> bool:
    """Over a unit and over the tolerated share of Meta's figure apart."""
    gap = abs(ours - theirs)
    return gap > 1 and gap * 100 > theirs * CHECK_TOLERANCE_PCT


def day_differs(ours: dict[str, int], theirs: dict[str, int]) -> bool:
    return any(apart(ours.get(name, 0), theirs.get(name, 0)) for name in CHECKED)


def check_account(db: Session, *, ad_account: AdAccount, today: date) -> CheckSummary:
    """Reads Meta's account total for the closed days and keeps the verdicts.

    Raises :class:`SyncFailed` as any read does; the caller decides whether
    a check that could not run stops anything.
    """
    from app.modules.metrics.services.sync import read_level

    if ad_account.provider != CHECKED_PROVIDER:
        return CheckSummary()
    since, until = check_range(today)
    theirs = network_days(
        read_level(db, ad_account, since=since, until=until, level=ACCOUNT_LEVEL)
    )
    ours = stored_days(db, ad_account=ad_account, since=since, until=until)
    empty = dict.fromkeys(CHECKED, 0)
    now = utcnow()
    made = []
    differing = []
    for day in sorted(set(theirs) | set(ours)):
        mine, meta = ours.get(day, empty), theirs.get(day, empty)
        differs = day_differs(mine, meta)
        if differs:
            differing.append(day)
        made.append(
            {
                "owner_id": ad_account.owner_id,
                "ad_account_id": ad_account.id,
                "day": day,
                "ours": mine,
                "theirs": meta,
                "differs": differs,
                "checked_at": now,
                "created_at": now,
                "updated_at": now,
            }
        )
    if made:
        statement = insert(MetricsCheck).values(made)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["ad_account_id", "day"],
                set_={
                    name: statement.excluded[name]
                    for name in (
                        "ours",
                        "theirs",
                        "differs",
                        "checked_at",
                        "updated_at",
                    )
                },
            )
        )
        db.commit()
    if differing:
        logger.warning(
            "figures for %s differ from Meta's account total on %s",
            ad_account.external_id,
            [one.isoformat() for one in differing],
        )
    return CheckSummary(days=len(made), differing=tuple(differing))


__all__ = [
    "CHECKED",
    "CheckSummary",
    "apart",
    "check_account",
    "check_range",
    "day_differs",
    "network_days",
    "stored_days",
]
