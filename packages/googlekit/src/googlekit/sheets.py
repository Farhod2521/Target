"""A spreadsheet this app writes into, and rows added to the bottom of it."""

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

SPREADSHEET_MIME: Final = "application/vnd.google-apps.spreadsheet"

_SPREADSHEET_FIELDS: Final = (
    "spreadsheetId,spreadsheetUrl,sheets.properties(sheetId,title)"
)
_CELL_FIELDS: Final = "userEnteredValue,userEnteredFormat.numberFormat"
_DRIVE_FIELDS: Final = "id,name,mimeType,trashed,capabilities/canEdit"
_DRIVE_PARAMS: Final = {"supportsAllDrives": "true"}


class SheetsClient:
    """One person's access token, and the spreadsheets it may touch."""

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
        """A new spreadsheet in the person's Drive, headings already in place."""
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
        """An existing spreadsheet, if this grant can still open it."""
        answer = self._call(
            "GET",
            f"{SHEETS_URL}/{spreadsheet_id}",
            params={"fields": _SPREADSHEET_FIELDS},
        )
        return as_spreadsheet(answer)

    def add_tab(
        self, *, spreadsheet_id: str, title: str, columns: Sequence[SheetColumn]
    ) -> str:
        """A tab added to a file that already exists, headed. Returns its id."""
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
        """Rows added below the last one with anything in it."""
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
        """Headings for columns that did not exist, inserted at index ``start``."""
        if not columns:
            return
        requests = inserted_columns(
            grid_id=_grid(sheet_id), start=start, columns=columns
        )
        self._batch(spreadsheet_id, requests)

    def first_column(self, *, spreadsheet_id: str, sheet_id: str) -> tuple[str, ...]:
        """Every value in column A under the heading row, top to bottom."""
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
        """What Drive knows about a file: its name, its kind, and two flags."""
        answer = self._call(
            "GET",
            f"{DRIVE_FILES_URL}/{file_id}",
            params={"fields": _DRIVE_FIELDS, **_DRIVE_PARAMS},
        )
        return as_drive_file(answer, file_id=file_id)

    def is_trashed(self, *, file_id: str) -> bool:
        """Whether the person moved this file to the bin."""
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
