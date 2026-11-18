"""The one chat's tools: the old look-ups as they are, five new ones, and
the note on how to read each result arriving with the result."""

from core.assistant.tools import (
    GAP_TOOL,
    HEALTH_TOOL,
    HELP_TOOL,
    PLANS_TOOL,
    READING,
    TICKET_TOOL,
    TOOL_NAMES,
    TOOLS,
    GapReport,
    TicketDraft,
    with_reading,
)
from core.chat.lookups import TOOLS as LOOKUPS


def test_the_old_look_ups_are_kept_and_five_are_added() -> None:
    assert {tool.name for tool in LOOKUPS} <= TOOL_NAMES
    assert {HEALTH_TOOL, HELP_TOOL, TICKET_TOOL, GAP_TOOL, PLANS_TOOL} <= TOOL_NAMES
    assert len(TOOLS) == len(LOOKUPS) + 5
    assert len(TOOL_NAMES) == len(TOOLS)


def test_a_result_arrives_with_how_to_read_it() -> None:
    assert with_reading("campaign_details", "X").startswith("How to read this:")
    assert with_reading("campaign_details", "X").endswith("\n\nX")
    assert with_reading("no_such", "X") == "X"
    assert set(READING) <= TOOL_NAMES


def test_a_ticket_says_what_was_checked_and_no_more_than_eight_lines() -> None:
    draft = TicketDraft(
        summary="To'lov o'tdi, tarif ochilmadi.", checked=["Tarif: yo'q"]
    )
    assert draft.checked == ["Tarif: yo'q"]
    schema = TicketDraft.model_json_schema()
    assert schema["properties"]["checked"]["maxItems"] == 8


def test_a_gap_is_words_to_write_or_something_to_build_and_stays_short() -> None:
    import pytest
    from pydantic import ValidationError

    report = GapReport(
        topic="Reklamani boshqa akkauntga ko'chirish",
        kind="tool",
        missing="Kampaniyani boshqa reklama akkauntiga ko'chiradigan amal kerak.",
    )
    assert report.kind == "tool"
    with pytest.raises(ValidationError):
        GapReport(topic="Savol", kind="other", missing="Nimadir kerak.")
    schema = GapReport.model_json_schema()
    assert schema["properties"]["missing"]["maxLength"] == 300
