"""What Claude is asked to return for one montage."""

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator
from videokit import Layout, Transition
from videokit.components import Component, components

TextPlace = Literal["top", "center", "bottom"]
SegmentRole = Literal["hook", "body", "proof", "offer", "cta"]
Framing = Literal["wide", "close"]

MAX_SEGMENTS = 40
MAX_TEXTS = 4
MAX_TEXT_CHARS = 60


class PlanSegment(BaseModel):
    """One stretch of the source to keep."""

    start: float = Field(ge=0, description="Second in the source where it starts.")
    end: float = Field(gt=0, description="Second in the source where it ends.")
    role: SegmentRole = Field(
        default="body", description="What this stretch does in the finished video."
    )
    framing: Framing = Field(
        default="wide",
        description="close = push in on the picture, for emphasis or to hide a jump.",
    )
    why: str = Field(default="", description="A few words: why this stretch is kept.")


class PlanText(BaseModel):
    """A line written over the finished video."""

    text: str = Field(
        min_length=1,
        max_length=MAX_TEXT_CHARS,
        description=f"At most {MAX_TEXT_CHARS} characters, in the video's language.",
    )
    at: float = Field(
        ge=0, description="Second in the FINISHED video where it appears."
    )
    seconds: float = Field(gt=0, le=8, description="How long it stays, at most 8.")
    place: TextPlace = "center"


class MontagePlan(BaseModel):
    """Claude's whole answer."""

    segments: list[PlanSegment] = Field(
        min_length=1,
        max_length=MAX_SEGMENTS,
        description="Kept stretches, in the order they should play.",
    )
    texts: list[PlanText] = Field(default_factory=list, max_length=MAX_TEXTS)
    summary: str = Field(
        description=(
            "Two short sentences in Uzbek for the owner: what the video now "
            "shows and what was left out."
        ),
    )


MAX_EVENTS = 12
MAX_EMPHASIS = 4


class PlanSegmentV3(PlanSegment):
    """A kept stretch, with how it is laid out and how it comes in."""

    layout: Layout = Field(
        default="full",
        description=(
            "full = the speaker fills the screen; split_top = the speaker in the "
            "bottom half and a panel on top (use only where a panel component is)."
        ),
    )
    transition_in: Transition = Field(
        default="none",
        description="How this stretch comes in. none for an ordinary cut; "
        "anything else only where the video moves to a new part.",
    )


class _Event(BaseModel):
    """One component on screen, anchored to the words it goes with."""

    model_config = ConfigDict(extra="forbid")

    anchor_word: int = Field(description="Number (#) of the word it appears on.")
    until_word: int = Field(description="Number (#) of the last word it stays for.")

    @model_validator(mode="after")
    def _ordered(self) -> "_Event":
        if self.until_word < self.anchor_word:
            raise ValueError("until_word must not come before anchor_word")
        return self


def plan_schema(*, word_count: int) -> type[BaseModel]:
    """The v3 answer's shape for a transcript of ``word_count`` words."""
    last = max(word_count - 1, 0)
    events = [
        _event_model(item, last=last)
        for item in components().values()
        if item.placement == "planner"
    ]
    event: Any = Annotated[Union[tuple(events)], Field(discriminator="component")]  # noqa: UP007
    return create_model(
        "MontagePlanV3",
        segments=(
            list[PlanSegmentV3],
            Field(min_length=1, max_length=MAX_SEGMENTS, description=_SEGMENTS),
        ),
        events=(
            list[event],
            Field(
                default_factory=list,
                max_length=MAX_EVENTS if word_count else 0,
                description=_EVENTS,
            ),
        ),
        emphasis=(
            list[Annotated[int, Field(ge=0, le=last)]],
            Field(
                default_factory=list,
                max_length=MAX_EMPHASIS if word_count else 0,
                description=_EMPHASIS,
            ),
        ),
        summary=(str, Field(description=_SUMMARY)),
    )


def _event_model(item: Component, *, last: int) -> type[BaseModel]:
    index = Annotated[int, Field(ge=0, le=last)]
    extra: dict[str, Any] = {}
    if item.beats:
        extra["beats"] = (
            beats_model(item, index) | None,
            Field(default=None, description=_BEATS),
        )
    return create_model(
        f"{_camel(item.name)}Event",
        __base__=_Event,
        component=(Literal[item.name], ...),
        zone=(Literal[item.zones], Field(default=item.zones[0])),
        anchor_word=(index, ...),
        until_word=(index, ...),
        props=(item.props_model(), ...),
        **extra,
    )


def beats_model(item: Component, index: Any) -> type[BaseModel]:
    """The word each of ``item``'s beats lands on; a list beat, one word
    per item. Every one may be left out."""
    fields: dict[str, Any] = {
        name: (
            (list[index] if item.beat_is_list(name) else index) | None,
            Field(default=None, description=what),
        )
        for name, what in item.beats
    }
    return create_model(
        f"{_camel(item.name)}Beats", __config__=ConfigDict(extra="forbid"), **fields
    )


def _camel(name: str) -> str:
    return name.title().replace("_", "")


_BEATS = (
    "Numbers (#) of the words each moment inside the component lands on. "
    "Leave one out and the component times it itself."
)
_SEGMENTS = "Kept stretches, in the order they should play."
_EVENTS = "Components on screen, each tied to the words it goes with."
_EMPHASIS = (
    "Numbers (#) of the words the picture punches in on: the point of a "
    "sentence - the price, the result, the punchline. Few, far apart."
)
_SUMMARY = (
    "Two short sentences in Uzbek for the owner: what the video now shows and "
    "what was left out."
)
