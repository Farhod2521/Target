import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from core.officeai.tools import (
    LOOKING,
    MONEY_TOOLS,
    TOOL_NAMES,
    TOOLS,
    CustomerQuery,
    Span,
    StatPart,
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
    known = TOOL_NAMES | set(get_args(StatPart)) | {"per_bar"}
    assert named <= known, named - known
    for name in MONEY_TOOLS:
        assert f"`{name}`" in text, name
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


def test_every_statistika_block_can_be_asked_for_and_only_a_few_at_once() -> None:
    from typing import get_args

    from app.modules.officeai.selectors.statistics import BLOCKS
    from core.officeai.tools import STAT_PARTS_AT_ONCE, Statistics, StatPart

    assert set(BLOCKS) == set(get_args(StatPart))
    with pytest.raises(ValidationError):
        Statistics.model_validate({"parts": []})
    with pytest.raises(ValidationError):
        Statistics.model_validate({"parts": ["funnel"] * (STAT_PARTS_AT_ONCE + 1)})
    with pytest.raises(ValidationError):
        Statistics.model_validate({"parts": ["passwords"]})
