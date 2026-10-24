"""The look-up catalogue: closed shapes, bounded windows, bounded results."""

import pytest
from pydantic import ValidationError

from core.chat.lookups import MAX_DAYS, TOOLS, CampaignList, clipped
from core.chat.verify import MARKER, FigureGate


def test_no_two_look_ups_share_a_name() -> None:
    names = [tool.name for tool in TOOLS]

    assert len(names) == len(set(names))


def test_every_look_up_refuses_a_key_it_did_not_declare() -> None:
    """An ``owner_id`` the model made up is a mistake, never a filter."""
    for tool in TOOLS:
        assert tool.as_param()["input_schema"]["additionalProperties"] is False

    with pytest.raises(ValidationError):
        CampaignList.model_validate({"owner_id": "someone-else"})


def test_a_window_longer_than_the_tables_hold_is_refused() -> None:
    with pytest.raises(ValidationError):
        CampaignList(days=MAX_DAYS + 1)


def test_a_long_result_is_cut_at_a_line_and_says_so() -> None:
    text = "\n".join(f"- row {index}" for index in range(2_000))

    cut = clipped(text, limit=100)

    *kept, note = cut.splitlines()
    assert note.startswith("(cut here")
    assert kept
    assert all(line.startswith("- row ") for line in kept)


def test_a_figure_allowed_half_way_through_passes_and_nothing_else_does() -> None:
    gate = FigureGate(allowed=frozenset({"15000"}))

    gate.allow(frozenset({"731"}))
    shown = gate.feed("731 va 15 000, lekin 999 ") + gate.flush()

    assert "731" in shown
    assert "15 000" in shown
    assert "999" not in shown
    assert MARKER in shown
    assert gate.masked == 1
