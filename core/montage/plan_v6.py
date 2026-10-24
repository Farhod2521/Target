"""What Claude is asked to return for a montage, from prompt v6 on.

**One shape for every montage.** The JSON schema the answer is held to
is sent with the request, and a request whose schema changes with the
transcript can never be served from the prompt cache. So nothing in the
schema depends on the montage: word numbers are any number from 0, and
the bounds that do depend on it - the last word, how many events a video
this short may hold - are checked by a validator once the answer is in
(:func:`plan_schema_v6`). A broken bound is handed back with its reason,
like any invalid answer (llmkit does that).

**One event shape for every graphic.** A union of one event per
component, each with its own props, compiles into a grammar the API
refuses as too large. So an event is a component's name, its words, its
props as ``{name, text}`` or ``{name, items}`` and its beats as
``{name, words}``; once the answer is in, each event is read into its
own component's model (props held to the manifest, beats to its names) -
and a wrong one is handed back like any other.

**The planner names words, not layouts.** v6 drops ``layout`` (a panel
brings its own) and ``why`` from a stretch; the code may change a
stretch's framing to hide a jump. The answer settles exactly like a v3
one (:func:`core.montage.settle.settle_v3` reads the same fields).
"""

from functools import cache
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    create_model,
    model_validator,
)
from videokit import Transition
from videokit.components import Component, components

from core.montage.plan import (
    MAX_EMPHASIS,
    MAX_SEGMENTS,
    Framing,
    SegmentRole,
    beats_model,
)

MAX_EVENTS_V6 = 20
# What the opening line is built on: the hook's kind.
HookType = Literal["number", "question", "claim", "result", "offer"]
Index = Annotated[int, Field(ge=0)]
_PROPS_HELP = "Its props by name: a text as {name, text}, a list as {name, items}."
_BEATS_HELP = (
    "Its beats by name, each with the number (#) of its word - one word per "
    "item for a list beat. Leave one out and the graphic times it itself."
)


class PlanSegmentV6(BaseModel):
    """A kept stretch: where, what it does, how close, how it comes in."""

    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0, description="Second in the source where it starts.")
    end: float = Field(gt=0, description="Second in the source where it ends.")
    role: SegmentRole = Field(description="What this stretch does in the video.")
    framing: Framing = Field(
        default="wide",
        description="close = pushed in a little; the code may change it.",
    )
    transition_in: Transition = Field(
        default="none",
        description="How it comes in; none for an ordinary cut.",
    )


class _EventV6(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_word: Index = Field(description="Number (#) of the word it appears on.")
    until_word: Index = Field(description="Number (#) of the last word it stays for.")


class PropV6(BaseModel):
    """One prop: a text, or a list of texts."""

    model_config = ConfigDict(extra="forbid")

    name: str
    text: str = ""
    items: list[str] = Field(default_factory=list)


class BeatV6(BaseModel):
    """One beat: its word, or one word per item for a list beat."""

    model_config = ConfigDict(extra="forbid")

    name: str
    words: list[Index] = Field(min_length=1)


class EventV6(BaseModel):
    """A graphic as the answer gives it, before it is read into its own
    component's model."""

    model_config = ConfigDict(extra="forbid")

    component: str = Field(description="The component's name, from the catalogue.")
    zone: str = Field(default="", description="One of its zones; empty: its first.")
    anchor_word: Index = Field(description="Number (#) of the word it appears on.")
    until_word: Index = Field(description="Number (#) of the last word it stays for.")
    props: list[PropV6] = Field(default_factory=list, description=_PROPS_HELP)
    beats: list[BeatV6] = Field(default_factory=list, description=_BEATS_HELP)

    @model_validator(mode="after")
    def _ordered(self) -> "EventV6":
        if self.until_word < self.anchor_word:
            raise ValueError("until_word must not come before anchor_word")
        return self


class _PlanV6(BaseModel):
    """Checks every word number against the transcript the plan was for."""

    model_config = ConfigDict(extra="forbid")
    # Set on each montage's class; never part of the schema.
    last_word: ClassVar[int] = -1

    @model_validator(mode="before")
    @classmethod
    def _as_answered(cls, data: Any) -> Any:
        """An answer read back from where it was kept: once read, each event
        is its component's own model, and kept that way its props and beats
        are by name - turned back into the lists the answer gave."""
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            return data
        return {**data, "events": [_answered(e) for e in data["events"]]}

    @model_validator(mode="after")
    def _bounded(self) -> "_PlanV6":
        events = getattr(self, "events", [])
        self.events = [typed_event(e) if isinstance(e, EventV6) else e for e in events]
        _check_words(self, last=type(self).last_word)
        return self


def _answered(event: Any) -> Any:
    """An event as the answer gives it: props and beats as lists."""
    if not isinstance(event, dict):
        return event
    props, beats = event.get("props"), event.get("beats")
    out = {**event}
    if isinstance(props, dict):
        out["props"] = [
            {"name": name, "items" if isinstance(value, list) else "text": value}
            for name, value in props.items()
            if value is not None
        ]
    if isinstance(beats, dict):
        out["beats"] = [
            {"name": name, "words": value if isinstance(value, list) else [value]}
            for name, value in beats.items()
            if value is not None
        ]
    elif beats is None:
        out.pop("beats", None)
    return out


def plan_schema_v6(*, word_count: int) -> type[BaseModel]:
    """The v6 answer's shape, with the bounds of a transcript of
    ``word_count`` words checked on the answer rather than in the schema."""
    model = create_model(
        "MontagePlanV6",
        __base__=_PlanV6,
        segments=(
            list[PlanSegmentV6],
            Field(min_length=1, max_length=MAX_SEGMENTS, description=_SEGMENTS),
        ),
        events=(
            list[EventV6],
            Field(default_factory=list, max_length=MAX_EVENTS_V6, description=_EVENTS),
        ),
        emphasis=(
            list[Index],
            Field(default_factory=list, max_length=MAX_EMPHASIS, description=_EMPHASIS),
        ),
        hook_type=(HookType, Field(description=_HOOK)),
        content_matches_brand=(bool, Field(description=_MATCHES)),
        summary=(str, Field(description=_SUMMARY)),
    )
    model.last_word = word_count - 1
    return model


def _check_words(plan: Any, *, last: int) -> None:
    """Every word number inside the transcript; none at all without one."""
    numbers = [*plan.emphasis]
    for event in plan.events:
        numbers += [event.anchor_word, event.until_word]
        beats = getattr(event, "beats", None)
        for value in (beats.model_dump(exclude_none=True) if beats else {}).values():
            numbers += value if isinstance(value, list) else [value]
    if last < 0 and (plan.events or plan.emphasis):
        raise ValueError("nothing is said in this video: no events, no emphasis")
    if bad := sorted({n for n in numbers if n > last}):
        raise ValueError(f"word numbers {bad} are past the last word, #{last}")


def typed_event(event: EventV6) -> BaseModel:
    """``event`` read into its component's own model: an unknown component,
    zone, prop or beat, or a prop out of its limits, is a ValueError."""
    planned = {c.name: c for c in components().values() if c.placement == "planner"}
    item = planned.get(event.component)
    if item is None:
        raise ValueError(
            f"no component {event.component!r}; one of {', '.join(planned)}"
        )
    props = {p.name: (p.items if p.items else p.text) for p in event.props}
    beats = {
        b.name: (b.words if item.beat_is_list(b.name) else b.words[0])
        for b in event.beats
    }
    try:
        return _read(item, event, props=props, beats=beats)
    except ValidationError as exc:
        raise ValueError(f"{item.name}: {exc}") from exc


def _read(
    item: Component, event: EventV6, *, props: dict[str, Any], beats: dict[str, Any]
) -> BaseModel:
    return _typed_models()[item.name].model_validate(
        {
            "component": item.name,
            "zone": event.zone or item.zones[0],
            "anchor_word": event.anchor_word,
            "until_word": event.until_word,
            "props": props,
            **({"beats": beats} if beats and item.beats else {}),
        }
    )


@cache
def _typed_models() -> dict[str, type[BaseModel]]:
    return {
        item.name: _event_model(item)
        for item in components().values()
        if item.placement == "planner"
    }


def _event_model(item: Component) -> type[BaseModel]:
    extra: dict[str, Any] = {}
    if item.beats:
        extra["beats"] = (
            beats_model(item, Index) | None,
            Field(default=None, description=_BEATS),
        )
    return create_model(
        f"{item.name.title().replace('_', '')}EventV6",
        __base__=_EventV6,
        component=(Literal[item.name], ...),
        zone=(Literal[item.zones], Field(default=item.zones[0])),
        props=(item.props_model(), ...),
        **extra,
    )


_SEGMENTS = "Kept stretches, in the order they should play."
_EVENTS = "Graphics on screen, each tied to the words it goes with."
_EMPHASIS = "Numbers (#) of the words the picture punches in on. Few, far apart."
_BEATS = (
    "Numbers (#) of the words each moment inside the graphic lands on. "
    "Leave one out and the graphic times it itself."
)
_HOOK = "What the opening line is built on."
_MATCHES = (
    "false when what is said does not fit the business described - another "
    "product, another trade, a video meant for someone else."
)
_SUMMARY = "Two short sentences for the owner, in the language the video speaks."


def plan_facts(plan: Any) -> dict[str, Any]:
    """What the answer said about the video as a whole, kept for staff and
    for reading many montages at once: the hook's kind, whether the video
    fits the business, each stretch's role and the graphics asked for."""
    return {
        "hook_type": getattr(plan, "hook_type", None),
        "content_matches_brand": getattr(plan, "content_matches_brand", None),
        "roles": [segment.role for segment in plan.segments],
        "components": [event.component for event in plan.events],
    }
