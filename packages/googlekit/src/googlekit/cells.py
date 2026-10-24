"""The shapes the Sheets requests carry: cells, headings, widths, tabs."""

import secrets
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from googlekit.models import SheetColumn

CELL_MAX_CHARS: Final = 50_000

DATE_TIME_PATTERN: Final = "dd.mm.yyyy hh:mm"

_DEFAULT_COLUMNS: Final = 26

_MAX_GRID_ID: Final = 2**31 - 2

_EPOCH: Final = datetime(1899, 12, 30)
_SECONDS_PER_DAY: Final = 86_400

type CellValue = str | int | float | datetime | None


def serial(moment: datetime) -> float:
    """``moment`` as Sheets counts it: days since 30 December 1899."""
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
    """A tab id to ask Google for, rather than one to be given."""
    return secrets.randbelow(_MAX_GRID_ID) + 1


def added_tab(
    *, grid_id: int, title: str, columns: Sequence[SheetColumn]
) -> list[Mapping[str, Any]]:
    """The requests that add a tab to a spreadsheet that already exists."""
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
    """The requests that insert ``columns`` at ``start``, headed and sized."""
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
