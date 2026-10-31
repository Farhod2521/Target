"""The day's reports as the morning message was built from them.

Kept for a few days, so a button pressed under the message opens the same
figures the reader is looking at, and a press does not build the whole day
again. **Kept only once final**: a report sent before the night's re-read is
built afresh on the next press, because the figures it waited for may have
arrived since.

The cache holds JSON, so the reports go in as plain dictionaries and come
back out as the same dataclasses.
"""

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.i18n import get_language
from app.modules.accounts.models import User
from app.modules.chat.selectors import cabinet_clock, daily_reports, report_day
from app.modules.notifications.constants import (
    DAILY_REPORTS_KEY,
    DAILY_REPORTS_TTL_SECONDS,
)
from core.chat.day_report import AdLine, DailyReport, Figure, GroupLine, Result


def day_reports(
    db: Session, *, owner: User, now: datetime, day: date | None = None
) -> list[DailyReport]:
    """Every chosen pair's day, the biggest spender first. ``day`` is the
    morning's unless a press or a command names its own."""
    clock = cabinet_clock(db, owner=owner)
    if clock is None:
        return []
    day = day or report_day(account=clock, now=now)
    key = DAILY_REPORTS_KEY.format(
        owner=owner.id, day=day.isoformat(), language=get_language()
    )
    kept = cache.get(key)
    if isinstance(kept, list) and kept:
        return [_loaded(row) for row in kept]
    reports = daily_reports(db, owner=owner, now=now, day=day)
    if reports and all(report.final for report in reports):
        cache.set(
            key,
            [_dumped(report) for report in reports],
            timeout=DAILY_REPORTS_TTL_SECONDS,
        )
    return reports


def _dumped(report: DailyReport) -> dict[str, Any]:
    row = asdict(report)
    row["day"] = report.day.isoformat()
    return row


def _loaded(row: dict[str, Any]) -> DailyReport:
    return DailyReport(
        **{
            **row,
            "day": date.fromisoformat(row["day"]),
            "figure": _figure(row["figure"]),
            "groups": tuple(
                GroupLine(
                    **{
                        **group,
                        "figure": _figure(group["figure"]),
                        "ads": tuple(
                            AdLine(name=ad["name"], figure=_figure(ad["figure"]))
                            for ad in group["ads"]
                        ),
                    }
                )
                for group in row["groups"]
            ),
            "other_currency": tuple(row["other_currency"]),
        }
    )


def _figure(row: dict[str, Any]) -> Figure:
    return Figure(
        **{**row, "results": tuple(Result(**result) for result in row["results"])}
    )


__all__ = ["day_reports"]
