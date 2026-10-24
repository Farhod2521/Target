"""What Google answered, turned into this package's DTOs.

:mod:`googlekit.sheets` holds the calls; this module and
:mod:`googlekit.cells` hold what goes out and what comes back.

**A tab id is a string outside this package.** Google's JSON carries a
number; here is where it stops being one.
"""

from collections.abc import Mapping
from typing import Any

from googlekit.errors import GoogleAPIError
from googlekit.models import DriveFile, Spreadsheet, Tab


def as_spreadsheet(answer: Mapping[str, Any]) -> Spreadsheet:
    """The fields a spreadsheet call asked for, as a DTO."""
    spreadsheet_id = str(answer.get("spreadsheetId") or "")
    if not spreadsheet_id:
        raise GoogleAPIError("the answer named no spreadsheet")
    tabs = [tab for tab in answer.get("sheets") or () if isinstance(tab, Mapping)]
    return Spreadsheet(
        spreadsheet_id=spreadsheet_id,
        url=str(answer.get("spreadsheetUrl") or ""),
        tabs=tuple(as_tab(tab) for tab in tabs),
    )


def as_tab(payload: Mapping[str, Any]) -> Tab:
    """One tab's properties.

    A tab's id defaults to zero and Google may leave a default out of its
    JSON, so a tab without one is tab 0 rather than no tab.
    """
    properties = payload.get("properties") or {}
    return Tab(
        sheet_id=str(int(properties.get("sheetId") or 0)),
        title=str(properties.get("title") or ""),
    )


def as_drive_file(answer: Mapping[str, Any], *, file_id: str) -> DriveFile:
    """Drive's answer about one file. See :class:`DriveFile` on ``canEdit``."""
    capabilities = answer.get("capabilities") or {}
    return DriveFile(
        file_id=str(answer.get("id") or file_id),
        name=str(answer.get("name") or ""),
        mime_type=str(answer.get("mimeType") or ""),
        trashed=bool(answer.get("trashed")),
        can_edit=bool(capabilities.get("canEdit", True)),
    )


def as_first_column(answer: Mapping[str, Any]) -> tuple[str, ...]:
    """Column A out of a data-filter answer. No ``values`` key means empty."""
    ranges = answer.get("valueRanges") or ()
    if not ranges or not isinstance(ranges[0], Mapping):
        return ()
    values = (ranges[0].get("valueRange") or {}).get("values") or ()
    column = values[0] if values else ()
    return tuple(str(value) for value in column if value not in ("", None))


__all__ = ["as_drive_file", "as_first_column", "as_spreadsheet", "as_tab"]
