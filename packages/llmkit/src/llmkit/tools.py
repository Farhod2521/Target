"""Tools Claude may call while it writes an answer, and what comes back."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from anthropic.types import ToolParam
from pydantic import BaseModel, ValidationError

SHOWN_PROBLEMS = 5


@dataclass(frozen=True, slots=True)
class Tool:
    """One tool: its name, what it is for, and the shape of its arguments."""

    name: str
    description: str
    arguments: type[BaseModel]

    def as_param(self) -> ToolParam:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": cast("Any", self.arguments.model_json_schema()),
        }


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A call the model made, with arguments already checked."""

    id: str
    name: str
    arguments: BaseModel


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """What the caller hands back. Text, because the model reads it."""

    text: str
    is_error: bool = False


ToolRunner = Callable[[ToolCall], ToolOutput]


def checked(
    *, tools: Mapping[str, Tool], call_id: str, name: str, raw: object
) -> ToolCall | ToolOutput:
    """The call, validated - or the output that explains why it was not run."""
    tool = tools.get(name)
    if tool is None:
        return ToolOutput(text=f"There is no tool called {name!r}.", is_error=True)
    try:
        arguments = tool.arguments.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or 'arguments'}: "
            f"{item['msg']}"
            for item in exc.errors()[:SHOWN_PROBLEMS]
        )
        return ToolOutput(text=f"Invalid arguments: {problems}", is_error=True)
    return ToolCall(id=call_id, name=name, arguments=arguments)


__all__ = ["Tool", "ToolCall", "ToolOutput", "ToolRunner", "checked"]
