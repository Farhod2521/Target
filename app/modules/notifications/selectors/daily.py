"""The day's or week's book as the morning message was built from it.

Kept for a few days, so a button pressed under the message opens the same
figures the reader is looking at, and a press does not build the whole day
again. **Kept only once final**: a report sent before the night's re-read is
built afresh on the next press, because the figures it waited for may have
arrived since.

The cache holds JSON, so the book goes in as plain dictionaries and comes back
out as the same dataclasses.
"""

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.i18n import get_language
from app.modules.accounts.models import User
from app.modules.chat.selectors import (
    cabinet_clock,
    current_day,
    daily_book,
    report_day,
    week_bounds,
    weekly_book,
)
from app.modules.notifications.constants import (
    DAILY_REPORTS_KEY,
    DAILY_REPORTS_TTL_SECONDS,
)
from core.chat.day_report import DailyReport, DayBook, DayTotal, Figure, Result


def day_book(
    db: Session, *, owner: User, now: datetime, day: date | None = None
) -> DayBook | None:
    """The owner's day. ``day`` is the morning's unless a press or a command
    names its own."""
    clock = cabinet_clock(db, owner=owner)
    if clock is None:
        return None
    day = day or report_day(account=clock, now=now)
    key = DAILY_REPORTS_KEY.format(
        owner=owner.id, day=day.isoformat(), language=get_language()
    )
    kept = cache.get(key)
    if isinstance(kept, dict) and kept:
        return _loaded(kept)
    book = daily_book(db, owner=owner, now=now, day=day)
    if book is not None and book.final:
        cache.set(key, _dumped(book), timeout=DAILY_REPORTS_TTL_SECONDS)
    return book


def week_book(
    db: Session, *, owner: User, now: datetime, since: date | None = None
) -> DayBook | None:
    """The owner's week. ``since`` is its Monday, the last finished week's
    unless a press names an older one."""
    clock = cabinet_clock(db, owner=owner)
    if clock is None:
        return None
    today = current_day(account=clock, now=now)
    since = since or week_bounds(today=today)[0]
    key = DAILY_REPORTS_KEY.format(
        owner=owner.id, day=f"week-{since.isoformat()}", language=get_language()
    )
    kept = cache.get(key)
    if isinstance(kept, dict) and kept:
        return _loaded(kept)
    book = weekly_book(db, owner=owner, now=now, since=since)
    if book is not None and book.final:
        cache.set(key, _dumped(book), timeout=DAILY_REPORTS_TTL_SECONDS)
    return book


def _dumped(book: DayBook) -> dict[str, Any]:
    row = asdict(book)
    row["day"] = book.day.isoformat()
    row["until"] = book.until.isoformat()
    for report in row["reports"]:
        report["day"] = report["day"].isoformat()
    return row


def _loaded(row: dict[str, Any]) -> DayBook:
    return DayBook(
        **{
            **row,
            "day": date.fromisoformat(row["day"]),
            "until": date.fromisoformat(row["until"]),
            "reports": tuple(_report(report) for report in row["reports"]),
            "totals": tuple(DayTotal(**total) for total in row["totals"]),
            "outside": tuple(row["outside"]),
        }
    )


def _report(row: dict[str, Any]) -> DailyReport:
    return DailyReport(
        **{
            **row,
            "day": date.fromisoformat(row["day"]),
            "figure": _figure(row["figure"]),
            "other_currency": tuple(row["other_currency"]),
        }
    )


def _figure(row: dict[str, Any]) -> Figure:
    return Figure(
        **{**row, "results": tuple(Result(**result) for result in row["results"])}
    )


__all__ = ["day_book", "week_book"]
