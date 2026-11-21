import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.officeai.tools import (
    LOOKING,
    MONEY_TOOLS,
    TOOL_NAMES,
    TOOLS,
    CustomerQuery,
    Span,
    tools_for,
)

PROMPT = Path(__file__).parents[3] / "core/agent/prompts/office_ai/v2.md"


def test_every_look_up_has_one_name_and_a_line_while_it_runs() -> None:
    assert len(TOOL_NAMES) == len(TOOLS)
    assert set(LOOKING) == TOOL_NAMES


def test_money_is_left_out_for_those_who_do_not_see_it() -> None:
    hidden = {tool.name for tool in tools_for(sees_money=False)}
    assert not hidden & MONEY_TOOLS
    assert {tool.name for tool in tools_for(sees_money=True)} == TOOL_NAMES


def test_the_prompt_names_only_look_ups_there_are() -> None:
    """What each look-up gives is said once, in its own description; the
    prompt names one only to say how to ask it."""
    text = PROMPT.read_text(encoding="utf-8")
    named = set(re.findall(r"`([a-z]+_[a-z_]+)`", text))
    assert named <= TOOL_NAMES | {"per_bar"}, named - TOOL_NAMES
    assert named >= MONEY_TOOLS
    assert "{{" not in text


def test_arguments_are_closed_and_bounded() -> None:
    assert Span().period == "30"
    with pytest.raises(ValidationError):
        Span.model_validate({"period": "week"})
    with pytest.raises(ValidationError):
        Span.model_validate({"days": 7})
    with pytest.raises(ValidationError):
        CustomerQuery.model_validate({"state": "rich"})
    assert CustomerQuery.model_validate({"state": "expiring"}).state == "expiring"
    assert CustomerQuery().limit == 10 and CustomerQuery().fields == []
    assert Span().per_bar is False
    with pytest.raises(ValidationError):
        CustomerQuery.model_validate({"limit": 31})
    with pytest.raises(ValidationError):
        CustomerQuery.model_validate({"fields": ["password"]})
