"""Tools Claude may call while it writes an answer, and what comes back.

The package knows how a tool round works - the call, the arguments, the
result handed back, the next round - and nothing about what any tool does.
The caller names its tools and runs them; this module only describes them
to the API and checks what the model sent before the caller ever sees it.

**Arguments are a pydantic model, checked here.** A model can send a
string where a number belongs, or a key nobody declared, and the caller
should not have to guard every tool against that. A call whose arguments
do not fit is answered with the problem instead of being run, so the model
can correct itself in the next round, and the caller's function is only
ever handed a validated instance.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from anthropic.types import ToolParam
from pydantic import BaseModel, ValidationError

# How many of a refusal's problems are handed back. Enough to fix a call;
# a call with more wrong fields than this was not an attempt at this tool.
SHOWN_PROBLEMS = 5


@dataclass(frozen=True, slots=True)
class Tool:
    """One tool: its name, what it is for, and the shape of its arguments.

    ``description`` is read by the model, not by a person, and it is the
    whole of what decides whether the tool is called: say what it returns
    and when to use it.
    """

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
    """What the caller hands back. Text, because the model reads it.

    ``is_error`` marks an output the model should treat as a refusal - a
    missing object, a limit reached - rather than as data.
    """

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
