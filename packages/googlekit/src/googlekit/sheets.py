"""A spreadsheet this app writes into, and rows added to the bottom of it.

Seven calls. Create a spreadsheet with its headings in place; describe
one, to learn whether an old id still opens and what its tabs are called;
add a tab to a file somebody picked themselves; append rows; insert
headings for columns that did not exist yesterday; read the first column
back. And two Drive questions - ``file_info`` and ``is_trashed`` - because
a file in the bin says nothing about being there, and a file this app did
not make may be the wrong kind or read-only.

What each request carries is :mod:`googlekit.cells`; what each answer
means is :mod:`googlekit.answers`.

**By tab id, never by tab name.** Everything that addresses a tab uses
``sheetId`` - the number Google assigns and nobody can edit. A1 notation
(``'Mijozlar'!A:K``), which most examples use, names the tab instead, and
a person renaming it would stop every write from that moment on.

**A tab id is a string outside this module.** Google's JSON carries a
number, and this is the one place that knows it: callers store and compare
the id the way they store every other id that comes from outside, and the
number is rebuilt only in the request body.
"""

from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any, Final, Self

import httpx

from googlekit.answers import as_drive_file, as_first_column, as_spreadsheet
from googlekit.cells import (
    CellValue,
    added_tab,
    cell,
    inserted_columns,
    new_grid_id,
    new_tab,
)
from googlekit.models import DriveFile, SheetColumn, Spreadsheet
from googlekit.transport import call, new_client

SHEETS_URL: Final = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_FILES_URL: Final = "https://www.googleapis.com/drive/v3/files"

# What Drive calls a spreadsheet. A person picking a file of their own can
# pick a document or a slide deck just as easily, and the answer to that is
# a sentence rather than a write that fails.
SPREADSHEET_MIME: Final = "application/vnd.google-apps.spreadsheet"

_SPREADSHEET_FIELDS: Final = (
    "spreadsheetId,spreadsheetUrl,sheets.properties(sheetId,title)"
)
_CELL_FIELDS: Final = "userEnteredValue,userEnteredFormat.numberFormat"
_DRIVE_FIELDS: Final = "id,name,mimeType,trashed,capabilities/canEdit"
# A shared drive is not the person's own, and Drive answers 404 for a file
# in one unless the request says it understands them. Without this, the
# company spreadsheet somebody picked reads as a file that is not there.
_DRIVE_PARAMS: Final = {"supportsAllDrives": "true"}


class SheetsClient:
    """One person's access token, and the spreadsheets it may touch.

    Holds an ``httpx.Client`` because a delivery run makes several calls in
    a row. Lend one to share a pool; otherwise this opens its own and
    closes it on exit.
    """

    def __init__(self, *, access_token: str, http: httpx.Client | None = None) -> None:
        if not access_token:
            raise ValueError("an access token is required")
        self._token = access_token
        self._http = http or new_client()
        self._owns_http = http is None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Only closes what it opened. A borrowed client stays open."""
        if self._owns_http:
            self._http.close()

    def create(
        self,
        *,
        title: str,
        sheet_title: str,
        columns: Sequence[SheetColumn],
        time_zone: str = "",
    ) -> Spreadsheet:
        """A new spreadsheet in the person's Drive, headings already in place.

        Headings bold and frozen, widths set, hidden columns hidden - all in
        one request, so there is never a spreadsheet out there that exists
        without its first row.

        ``time_zone`` is the spreadsheet's own, the one ``NOW()`` reads.
        Blank leaves Google's default, which is the creator's.
        """
        properties: dict[str, Any] = {"title": title}
        if time_zone:
            properties["timeZone"] = time_zone
        answer = self._call(
            "POST",
            SHEETS_URL,
            json={"properties": properties, "sheets": [new_tab(sheet_title, columns)]},
            params={"fields": _SPREADSHEET_FIELDS},
        )
        return as_spreadsheet(answer)

    def describe(self, *, spreadsheet_id: str) -> Spreadsheet:
        """An existing spreadsheet, if this grant can still open it.

        :class:`SheetMissing` when it was deleted for good;
        :class:`PermissionMissing` when it exists and this grant may not
        touch it.
        """
        answer = self._call(
            "GET",
            f"{SHEETS_URL}/{spreadsheet_id}",
            params={"fields": _SPREADSHEET_FIELDS},
        )
        return as_spreadsheet(answer)

    def add_tab(
        self, *, spreadsheet_id: str, title: str, columns: Sequence[SheetColumn]
    ) -> str:
        """A tab added to a file that already exists, headed. Returns its id.

        For a spreadsheet the person picked themselves: what they already
        have in the file is left exactly as it is, and this app writes only
        into the tab it added.

        The id is chosen here rather than read back afterwards - see
        :func:`googlekit.cells.new_grid_id` - so that the tab, its headings
        and its widths arrive in one request and there is never a tab out
        there with no first row.

        ``title`` has to be one the file does not already carry; Sheets
        refuses a second tab with the same name, and :meth:`describe` is
        what the caller compares against.
        """
        grid_id = new_grid_id()
        self._batch(
            spreadsheet_id, added_tab(grid_id=grid_id, title=title, columns=columns)
        )
        return str(grid_id)

    def append(
        self,
        *,
        spreadsheet_id: str,
        sheet_id: str,
        rows: Sequence[Sequence[CellValue]],
    ) -> None:
        """Rows added below the last one with anything in it.

        One request for the whole batch, applied or refused whole - there
        is no half-written batch to reason about. What there can be is a
        timeout after sending, which arrives as ``OutcomeUnknown``.
        """
        if not rows:
            return
        append = {
            "sheetId": _grid(sheet_id),
            "rows": [{"values": [cell(value) for value in row]} for row in rows],
            "fields": _CELL_FIELDS,
        }
        self._batch(spreadsheet_id, [{"appendCells": append}])

    def add_columns(
        self,
        *,
        spreadsheet_id: str,
        sheet_id: str,
        start: int,
        columns: Sequence[SheetColumn],
    ) -> None:
        """Headings for columns that did not exist, inserted at index ``start``.

        Inserted, never written over what is there. ``start`` is just past
        the last column the caller owns, and the person may have added one
        of their own in that place - a "called back" column is the commonest
        thing done to a spreadsheet like this. It moves right, keeping its
        heading and every value in it. A heading written at ``start``
        instead would have taken it over, and every row after would have
        put answers into it.

        The grid grows by the inserted columns, so it never runs out of room
        however many questions a form picks up.
        """
        if not columns:
            return
        requests = inserted_columns(
            grid_id=_grid(sheet_id), start=start, columns=columns
        )
        self._batch(spreadsheet_id, requests)

    def first_column(self, *, spreadsheet_id: str, sheet_id: str) -> tuple[str, ...]:
        """Every value in column A under the heading row, top to bottom.

        Read by tab id through a data filter, for the module note's reason.
        Blank cells are dropped: the caller asks whether a value is there,
        and an empty row somebody left in the middle does not answer that.
        """
        grid = {
            "sheetId": _grid(sheet_id),
            "startRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        }
        answer = self._call(
            "POST",
            f"{SHEETS_URL}/{spreadsheet_id}/values:batchGetByDataFilter",
            json={"dataFilters": [{"gridRange": grid}], "majorDimension": "COLUMNS"},
        )
        return as_first_column(answer)

    def file_info(self, *, file_id: str) -> DriveFile:
        """What Drive knows about a file: its name, its kind, and two flags.

        Asked of a file somebody picked themselves, before anything is
        written into it. The three answers that stop a write - it is in the
        bin, it is not a spreadsheet, they may only read it - are a
        different sentence each on the screen, and a write that failed
        cannot tell them apart.
        """
        answer = self._call(
            "GET",
            f"{DRIVE_FILES_URL}/{file_id}",
            params={"fields": _DRIVE_FIELDS, **_DRIVE_PARAMS},
        )
        return as_drive_file(answer, file_id=file_id)

    def is_trashed(self, *, file_id: str) -> bool:
        """Whether the person moved this file to the bin.

        Nothing else says so. A spreadsheet in the bin can go on accepting
        writes while its owner believes it is gone, until Drive empties the
        bin and the next write fails with a 404 a month later.
        """
        return self.file_info(file_id=file_id).trashed

    def _batch(
        self, spreadsheet_id: str, requests: Sequence[Mapping[str, Any]]
    ) -> None:
        self._call(
            "POST",
            f"{SHEETS_URL}/{spreadsheet_id}:batchUpdate",
            json={"requests": list(requests)},
            params={"fields": "spreadsheetId"},
        )

    def _call(
        self,
        method: str,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return call(
            self._http, method, url, token=self._token, json=json, params=params
        )


def _grid(sheet_id: str) -> int:
    """A tab id as the request body carries it. See the module note."""
    return int(sheet_id)


__all__ = ["DRIVE_FILES_URL", "SHEETS_URL", "SPREADSHEET_MIME", "SheetsClient"]
