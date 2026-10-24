"""The shapes the Sheets requests carry: cells, headings, widths, tabs.

:mod:`googlekit.sheets` holds the calls; this module holds what they
send. Nothing here talks to Google, and every tab id here is
the number Google's JSON wants - :mod:`googlekit.sheets` turns the string
its callers hold into it.

**Strings are strings.** Every text cell goes in as ``stringValue``, which
Sheets stores exactly as given. Letting Sheets parse its input instead
turns an answer that starts with ``=`` into a formula a stranger wrote
into this person's spreadsheet, and a telephone number that starts with
``+`` into a number with its plus sign gone.
"""

import secrets
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from googlekit.models import SheetColumn

# Google's ceiling on one cell. No answer on a lead form comes near it, and
# a cell over it fails the whole batch - so it is cut rather than trusted:
# one row nobody can write would hold up every row behind it.
CELL_MAX_CHARS: Final = 50_000

# How a moment reads in a cell. Day first, like the product's own screens,
# with a real date underneath so the column sorts by time and not as text.
DATE_TIME_PATTERN: Final = "dd.mm.yyyy hh:mm"

# What a new spreadsheet opens with. Kept as a floor, so a sheet created
# with a handful of columns still has room to the right of them.
_DEFAULT_COLUMNS: Final = 26

# The largest tab id worth asking for. Google's own is a signed 32-bit
# number, and ``new_grid_id`` picks one at random out of this range.
_MAX_GRID_ID: Final = 2**31 - 2

# The day Sheets counts from: a date is the number of days since this one,
# and the time of day is the fraction. Excel's scheme, epoch included.
_EPOCH: Final = datetime(1899, 12, 30)
_SECONDS_PER_DAY: Final = 86_400

type CellValue = str | int | float | datetime | None


def serial(moment: datetime) -> float:
    """``moment`` as Sheets counts it: days since 30 December 1899.

    Read as a wall clock. An offset, if there is one, is dropped rather
    than applied - a cell has no timezone, so the caller converts to the
    reader's local time first and this writes down what their clock said.
    """
    delta = moment.replace(tzinfo=None) - _EPOCH
    seconds = delta.seconds + delta.microseconds / 1_000_000
    return delta.days + seconds / _SECONDS_PER_DAY


def cell(value: CellValue) -> dict[str, Any]:
    """One value as Sheets' ``CellData``. See the module note on strings."""
    if value is None or value == "":
        return {}
    if isinstance(value, datetime):
        date_format = {"type": "DATE_TIME", "pattern": DATE_TIME_PATTERN}
        return {
            "userEnteredValue": {"numberValue": serial(value)},
            "userEnteredFormat": {"numberFormat": date_format},
        }
    if isinstance(value, str):
        return {"userEnteredValue": {"stringValue": value[:CELL_MAX_CHARS]}}
    return {"userEnteredValue": {"numberValue": value}}


def new_tab(title: str, columns: Sequence[SheetColumn]) -> dict[str, Any]:
    """The one tab of a new spreadsheet: headings bold and frozen, widths set."""
    grid = {
        "startRow": 0,
        "startColumn": 0,
        "rowData": [{"values": [_heading(column.header) for column in columns]}],
        "columnMetadata": [_dimension(column) for column in columns],
    }
    return {
        "properties": {
            "title": title,
            "gridProperties": {
                "frozenRowCount": 1,
                "columnCount": max(_DEFAULT_COLUMNS, len(columns)),
            },
        },
        "data": [grid],
    }


def new_grid_id() -> int:
    """A tab id to ask Google for, rather than one to be given.

    Chosen here so that a whole tab - the sheet, its headings, its widths -
    arrives in one batch. A request that added the tab and then asked what
    its id was could not carry the headings in the same call, and a tab
    without its first row is one the next run appends rows underneath.

    A collision is possible and is deliberately not handled: the batch is
    refused whole, nothing is created, and the caller's next attempt picks
    another number out of two thousand million.
    """
    return secrets.randbelow(_MAX_GRID_ID) + 1


def added_tab(
    *, grid_id: int, title: str, columns: Sequence[SheetColumn]
) -> list[Mapping[str, Any]]:
    """The requests that add a tab to a spreadsheet that already exists.

    The tab :func:`new_tab` describes, in the shape a batch update takes
    rather than the shape a new file takes: ``addSheet`` carries properties
    and no cells, so the headings and the widths follow it in the same
    batch, under the id the caller chose.
    """
    properties = {
        "sheetId": grid_id,
        "title": title,
        "gridProperties": {
            "frozenRowCount": 1,
            "columnCount": max(_DEFAULT_COLUMNS, len(columns)),
        },
    }
    headings = {
        "start": {"sheetId": grid_id, "rowIndex": 0, "columnIndex": 0},
        "rows": [{"values": [_heading(column.header) for column in columns]}],
        "fields": "userEnteredValue,userEnteredFormat.textFormat.bold",
    }
    requests: list[Mapping[str, Any]] = [
        {"addSheet": {"properties": properties}},
        {"updateCells": headings},
    ]
    requests.extend(
        _resize(grid_id=grid_id, index=index, column=column)
        for index, column in enumerate(columns)
    )
    return requests


def inserted_columns(
    *, grid_id: int, start: int, columns: Sequence[SheetColumn]
) -> list[Mapping[str, Any]]:
    """The requests that insert ``columns`` at ``start``, headed and sized.

    Formatted like the column before - the caller's last - rather than like
    the person's own. Google needs a column there to copy, hence the check.
    """
    span = {
        "sheetId": grid_id,
        "dimension": "COLUMNS",
        "startIndex": start,
        "endIndex": start + len(columns),
    }
    headings = {
        "start": {"sheetId": grid_id, "rowIndex": 0, "columnIndex": start},
        "rows": [{"values": [_heading(column.header) for column in columns]}],
        "fields": "userEnteredValue,userEnteredFormat.textFormat.bold",
    }
    requests: list[Mapping[str, Any]] = [
        {"insertDimension": {"range": span, "inheritFromBefore": start > 0}},
        {"updateCells": headings},
    ]
    requests.extend(
        _resize(grid_id=grid_id, index=start + offset, column=column)
        for offset, column in enumerate(columns)
    )
    return requests


def _heading(text: str) -> dict[str, Any]:
    """A heading cell: plain text, bold."""
    return {
        "userEnteredValue": {"stringValue": text[:CELL_MAX_CHARS]},
        "userEnteredFormat": {"textFormat": {"bold": True}},
    }


def _dimension(column: SheetColumn) -> dict[str, Any]:
    """How wide a column opens, and whether it shows at all."""
    return {"pixelSize": column.width_px, "hiddenByUser": column.hidden}


def _resize(*, grid_id: int, index: int, column: SheetColumn) -> dict[str, Any]:
    """The request that gives one existing column its width."""
    span = {
        "sheetId": grid_id,
        "dimension": "COLUMNS",
        "startIndex": index,
        "endIndex": index + 1,
    }
    return {
        "updateDimensionProperties": {
            "range": span,
            "properties": _dimension(column),
            "fields": "pixelSize,hiddenByUser",
        }
    }


__all__ = [
    "CELL_MAX_CHARS",
    "DATE_TIME_PATTERN",
    "CellValue",
    "added_tab",
    "cell",
    "inserted_columns",
    "new_grid_id",
    "new_tab",
    "serial",
]
