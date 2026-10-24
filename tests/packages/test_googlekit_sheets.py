"""googlekit.sheets: creating, appending, reading back, and the error split.

No Django, no database, no network - an ``httpx.MockTransport`` answers
every request, like the rest of this directory.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from googlekit import (
    CELL_MAX_CHARS,
    DATE_TIME_PATTERN,
    GoogleAPIError,
    GoogleError,
    OutcomeUnknown,
    PermissionMissing,
    RateLimited,
    SheetColumn,
    SheetMissing,
    SheetsClient,
    TabMissing,
    Unavailable,
    serial,
)

TOKEN = "ya29.access-token-nobody-should-see"
CREATED = {
    "spreadsheetId": "sp1",
    "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sp1/edit",
    "sheets": [{"properties": {"sheetId": 0}}],
}


def answering(
    payload: dict[str, Any] | None = None,
    *,
    status: int = 200,
    seen: list[httpx.Request] | None = None,
) -> SheetsClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload if payload is not None else {})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SheetsClient(access_token=TOKEN, http=http)


def raising(error: Exception) -> SheetsClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SheetsClient(access_token=TOKEN, http=http)


def body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def appended(seen: list[httpx.Request]) -> list[dict[str, Any]]:
    """The cells of the first appended row."""
    request = body(seen[0])["requests"][0]["appendCells"]
    return request["rows"][0]["values"]


def append_one(client: SheetsClient, row: list[Any]) -> None:
    client.append(spreadsheet_id="sp1", sheet_id="0", rows=[row])


# --- Creating --------------------------------------------------------------


def test_create_puts_headings_widths_and_the_hidden_column_in_one_request() -> None:
    """There is never a spreadsheet out there without its first row."""
    seen: list[httpx.Request] = []
    columns = [
        SheetColumn(header="ID", width_px=40, hidden=True),
        SheetColumn(header="Ism", width_px=180),
    ]

    made = answering(CREATED, seen=seen).create(
        title="Mijozlar",
        sheet_title="Lidlar",
        columns=columns,
        time_zone="Europe/Berlin",
    )

    assert (made.spreadsheet_id, made.sheet_ids) == ("sp1", ("0",))
    assert made.url.endswith("/sp1/edit")
    assert len(seen) == 1
    sent = body(seen[0])
    assert sent["properties"] == {"title": "Mijozlar", "timeZone": "Europe/Berlin"}
    sheet = sent["sheets"][0]
    assert sheet["properties"]["title"] == "Lidlar"
    assert sheet["properties"]["gridProperties"]["frozenRowCount"] == 1
    grid = sheet["data"][0]
    headings = grid["rowData"][0]["values"]
    assert [cell["userEnteredValue"]["stringValue"] for cell in headings] == [
        "ID",
        "Ism",
    ]
    assert all(cell["userEnteredFormat"]["textFormat"]["bold"] for cell in headings)
    assert grid["columnMetadata"] == [
        {"pixelSize": 40, "hiddenByUser": True},
        {"pixelSize": 180, "hiddenByUser": False},
    ]
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_create_leaves_the_timezone_to_google_when_none_is_known() -> None:
    seen: list[httpx.Request] = []

    answering(CREATED, seen=seen).create(
        title="Mijozlar", sheet_title="Lidlar", columns=[SheetColumn(header="Ism")]
    )

    assert "timeZone" not in body(seen[0])["properties"]


def test_a_tab_whose_id_google_left_out_is_tab_zero() -> None:
    answer = {"spreadsheetId": "sp1", "sheets": [{"properties": {}}]}

    made = answering(answer).create(title="t", sheet_title="s", columns=[])

    assert made.sheet_ids == ("0",)


def test_an_answer_that_names_no_spreadsheet_is_refused() -> None:
    with pytest.raises(GoogleAPIError):
        answering({"sheets": []}).describe(spreadsheet_id="sp1")


def test_describe_lists_every_tab() -> None:
    seen: list[httpx.Request] = []
    answer = {
        "spreadsheetId": "sp1",
        "sheets": [{"properties": {"sheetId": 0}}, {"properties": {"sheetId": 77}}],
    }

    found = answering(answer, seen=seen).describe(spreadsheet_id="sp1")

    assert found.sheet_ids == ("0", "77")
    assert seen[0].method == "GET"


# --- Appending -------------------------------------------------------------


def test_text_is_written_as_text_whatever_it_looks_like() -> None:
    """A formula a stranger typed into a form must not run in this sheet."""
    seen: list[httpx.Request] = []

    append_one(
        answering(seen=seen), ['=HYPERLINK("http://evil.test")', "+15550100", "007"]
    )

    assert [cell["userEnteredValue"] for cell in appended(seen)] == [
        {"stringValue": '=HYPERLINK("http://evil.test")'},
        {"stringValue": "+15550100"},
        {"stringValue": "007"},
    ]


def test_append_addresses_the_tab_by_id_not_by_name() -> None:
    seen: list[httpx.Request] = []

    answering(seen=seen).append(spreadsheet_id="sp1", sheet_id="42", rows=[["x"]])

    assert body(seen[0])["requests"][0]["appendCells"]["sheetId"] == 42
    assert seen[0].url.path.endswith("/sp1:batchUpdate")


def test_a_moment_is_a_real_date_with_a_format() -> None:
    seen: list[httpx.Request] = []
    moment = datetime(2026, 9, 10, 18, 30)

    append_one(answering(seen=seen), [moment])

    cell = appended(seen)[0]
    assert cell["userEnteredValue"] == {"numberValue": serial(moment)}
    assert cell["userEnteredFormat"]["numberFormat"] == {
        "type": "DATE_TIME",
        "pattern": DATE_TIME_PATTERN,
    }


def test_blank_and_missing_values_are_empty_cells() -> None:
    seen: list[httpx.Request] = []

    append_one(answering(seen=seen), ["", None, 5])

    assert appended(seen) == [{}, {}, {"userEnteredValue": {"numberValue": 5}}]


def test_an_oversized_cell_is_cut_rather_than_refused() -> None:
    """One cell over Google's ceiling would fail every row in the batch."""
    seen: list[httpx.Request] = []

    append_one(answering(seen=seen), ["x" * (CELL_MAX_CHARS + 10)])

    assert len(appended(seen)[0]["userEnteredValue"]["stringValue"]) == CELL_MAX_CHARS


def test_nothing_to_append_sends_nothing() -> None:
    seen: list[httpx.Request] = []

    answering(seen=seen).append(spreadsheet_id="sp1", sheet_id="0", rows=[])

    assert seen == []


# --- Dates -----------------------------------------------------------------


def test_serial_counts_days_from_the_sheets_epoch() -> None:
    assert serial(datetime(1899, 12, 31)) == 1
    assert serial(datetime(1900, 1, 1, 12)) == 2.5


def test_serial_reads_the_wall_clock_and_drops_the_offset() -> None:
    """The caller converts to local time; a cell has no timezone to keep."""
    local = datetime(2026, 9, 10, 9, 0, tzinfo=timezone(timedelta(hours=5)))

    assert serial(local) == serial(datetime(2026, 9, 10, 9, 0))


# --- New columns -----------------------------------------------------------


def test_new_headings_are_inserted_so_the_persons_own_column_moves_right() -> None:
    """Written at ``start`` instead, a heading would take their column over."""
    seen: list[httpx.Request] = []

    answering(seen=seen).add_columns(
        spreadsheet_id="sp1",
        sheet_id="3",
        start=11,
        columns=[SheetColumn(header="Qaysi tuman?", width_px=170)],
    )

    requests = body(seen[0])["requests"]
    inserted = {"sheetId": 3, "dimension": "COLUMNS", "startIndex": 11, "endIndex": 12}
    assert requests[0] == {
        "insertDimension": {"range": inserted, "inheritFromBefore": True}
    }
    assert not any("appendDimension" in request for request in requests)
    headings = requests[1]["updateCells"]
    assert headings["start"] == {"sheetId": 3, "rowIndex": 0, "columnIndex": 11}
    assert headings["rows"][0]["values"][0]["userEnteredValue"] == {
        "stringValue": "Qaysi tuman?"
    }
    span = requests[2]["updateDimensionProperties"]["range"]
    assert (span["startIndex"], span["endIndex"]) == (11, 12)


def test_no_new_columns_sends_nothing() -> None:
    seen: list[httpx.Request] = []

    answering(seen=seen).add_columns(
        spreadsheet_id="sp1", sheet_id="0", start=5, columns=[]
    )

    assert seen == []


# --- Reading back ----------------------------------------------------------


def test_first_column_reads_by_tab_id_and_drops_blanks() -> None:
    seen: list[httpx.Request] = []
    answer = {"valueRanges": [{"valueRange": {"values": [["id-1", "", "id-2"]]}}]}

    found = answering(answer, seen=seen).first_column(
        spreadsheet_id="sp1", sheet_id="9"
    )

    assert found == ("id-1", "id-2")
    grid = body(seen[0])["dataFilters"][0]["gridRange"]
    assert (grid["sheetId"], grid["startRowIndex"]) == (9, 1)


def test_first_column_of_a_sheet_with_only_headings_is_empty() -> None:
    answer = {"valueRanges": [{"valueRange": {"range": "A2:A"}}]}

    assert answering(answer).first_column(spreadsheet_id="sp1", sheet_id="0") == ()


def test_is_trashed_reads_the_drive_flag() -> None:
    assert answering({"trashed": True}).is_trashed(file_id="sp1") is True
    assert answering({}).is_trashed(file_id="sp1") is False


# --- A file the owner picked ---------------------------------------------


def test_file_info_reads_what_stops_a_write() -> None:
    answer = {
        "id": "sp1",
        "name": "Sotuvlar",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "trashed": False,
        "capabilities": {"canEdit": False},
    }
    seen: list[httpx.Request] = []

    found = answering(answer, seen=seen).file_info(file_id="sp1")

    assert (found.name, found.can_edit, found.trashed) == ("Sotuvlar", False, False)
    # Shared drives answer only when asked to.
    assert seen[0].url.params["supportsAllDrives"] == "true"


def test_file_info_without_capabilities_reads_as_writable() -> None:
    """The write itself is the authority; a left-out field does not refuse it."""
    assert answering({"id": "sp1"}).file_info(file_id="sp1").can_edit is True


def test_a_tab_arrives_with_its_headings_in_one_request() -> None:
    seen: list[httpx.Request] = []
    columns = [SheetColumn(header="ID", hidden=True), SheetColumn(header="Ism")]

    tab = answering({}, seen=seen).add_tab(
        spreadsheet_id="sp1", title="TargetologAI — Mijozlar", columns=columns
    )

    assert len(seen) == 1
    requests = body(seen[0])["requests"]
    added = requests[0]["addSheet"]["properties"]
    assert (str(added["sheetId"]), added["title"]) == (tab, "TargetologAI — Mijozlar")
    heading = requests[1]["updateCells"]
    assert str(heading["start"]["sheetId"]) == tab
    cells = heading["rows"][0]["values"]
    assert [cell["userEnteredValue"]["stringValue"] for cell in cells] == ["ID", "Ism"]


def test_describe_names_every_tab() -> None:
    answer = {
        "spreadsheetId": "sp1",
        "sheets": [
            {"properties": {"sheetId": 0, "title": "Sotuvlar"}},
            {"properties": {"sheetId": 9, "title": "TargetologAI — Mijozlar"}},
        ],
    }

    found = answering(answer).describe(spreadsheet_id="sp1")

    assert found.titles == frozenset({"Sotuvlar", "TargetologAI — Mijozlar"})


# --- The error split -------------------------------------------------------


def test_a_lost_tab_is_still_a_lost_sheet_to_those_who_ask_only_that() -> None:
    assert issubclass(TabMissing, SheetMissing)


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (
            404,
            {"error": {"code": 404, "message": "Requested entity was not found."}},
            SheetMissing,
        ),
        (
            400,
            {
                "error": {
                    "code": 400,
                    "message": "Invalid requests[0].appendCells: No grid with id: 5",
                }
            },
            TabMissing,
        ),
        (
            403,
            {
                "error": {
                    "code": 403,
                    "message": "No permission",
                    "status": "PERMISSION_DENIED",
                }
            },
            PermissionMissing,
        ),
        (
            403,
            {"error": {"code": 403, "errors": [{"reason": "accessNotConfigured"}]}},
            GoogleAPIError,
        ),
        (
            403,
            {"error": {"code": 403, "details": [{"reason": "SERVICE_DISABLED"}]}},
            GoogleAPIError,
        ),
        (
            403,
            {"error": {"code": 403, "errors": [{"reason": "userRateLimitExceeded"}]}},
            RateLimited,
        ),
        (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}, RateLimited),
        (401, {"error": {"code": 401, "status": "UNAUTHENTICATED"}}, Unavailable),
        (503, {"error": {"code": 503}}, Unavailable),
        (400, {"error": {"code": 400, "message": "Invalid value"}}, GoogleAPIError),
    ],
)
def test_failures_are_split_by_what_the_caller_does(
    status: int, payload: dict[str, Any], expected: type[GoogleError]
) -> None:
    with pytest.raises(expected):
        append_one(answering(payload, status=status), ["x"])


def test_a_401_is_not_a_lost_grant() -> None:
    """The refresh that follows is what says whether the grant is gone."""
    with pytest.raises(Unavailable) as caught:
        append_one(answering({"error": {"code": 401}}, status=401), ["x"])

    assert not isinstance(caught.value, PermissionMissing)


def test_a_rate_limit_is_temporary() -> None:
    assert issubclass(RateLimited, Unavailable)


def test_a_request_that_never_left_is_safe_to_retry() -> None:
    with pytest.raises(Unavailable) as caught:
        append_one(raising(httpx.ConnectError("refused")), ["x"])

    assert not isinstance(caught.value, OutcomeUnknown)


def test_a_request_whose_answer_was_lost_is_an_unknown_outcome() -> None:
    """The row may be in the sheet; retrying blindly would write it twice."""
    with pytest.raises(OutcomeUnknown):
        append_one(raising(httpx.ReadTimeout("slow")), ["x"])


def test_an_error_page_that_is_not_json_is_temporary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad gateway</html>")

    client = SheetsClient(
        access_token=TOKEN, http=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(Unavailable):
        append_one(client, ["x"])


@pytest.mark.parametrize(
    "client",
    [
        pytest.param(
            lambda: answering({"error": {"message": "denied"}}, status=403),
            id="refused",
        ),
        pytest.param(lambda: raising(httpx.ReadTimeout("slow")), id="timeout"),
    ],
)
def test_no_failure_message_carries_the_token(client: Any) -> None:
    with pytest.raises(GoogleError) as caught:
        append_one(client(), ["x"])

    assert TOKEN not in str(caught.value)


def test_the_client_refuses_an_empty_token() -> None:
    with pytest.raises(ValueError, match="access token"):
        SheetsClient(access_token="")
