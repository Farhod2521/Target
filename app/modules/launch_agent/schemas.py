import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.launch_agent.constants import MAX_TEXT_CHARS


class TurnIn(BaseModel):
    """One message, or one press. A press carries the button's ``slot`` and
    ``value`` exactly as the last answer gave them."""

    text: str = Field("", max_length=MAX_TEXT_CHARS * 2)
    slot: str = Field("", max_length=16)
    value: str = Field("", max_length=1000)
    asset_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="With `slot: media`: library tiles ticked in the picker.",
    )

    @model_validator(mode="after")
    def _one_of(self) -> "TurnIn":
        if not self.slot and not self.text.strip():
            raise ValueError("Xabar yozing yoki tugmani bosing.")
        return self


class LaunchChatOptionOut(BaseModel):
    label: str
    slot: str
    value: str
    recommended: bool = False
    opens: Literal["", "media", "upload", "review", "form"] = Field(
        "",
        description=(
            "Not empty: the press opens one of the cabinet's own windows instead "
            "of sending a turn. `media`: the media picker. `upload`: the file "
            "upload. `review`: the review screen. `form`: the lead form dialog."
        ),
    )


class LaunchChatAskOut(BaseModel):
    slot: str
    text: str
    options: list[LaunchChatOptionOut] = []
    input: Literal["text", "url", "phone", "money", "none"] = Field(
        description="The kind of box to type in. `none`: buttons, typing still taken."
    )
    hint: str = ""


class LaunchChatChipOut(BaseModel):
    slot: str
    label: str
    value: str


class LaunchChatMessageOut(BaseModel):
    author: Literal["user", "agent"]
    text: str
    at: str = ""


class VoiceOut(BaseModel):
    """A recording's words, for the message box - not sent as a message."""

    text: str
    language: str = ""


class LaunchChatCardAdvertOut(BaseModel):
    primary_text: str
    headline: str


class LaunchChatCardOut(BaseModel):
    """What was prepared, short enough for a chat. The review screen has
    the whole of it."""

    name: str = Field(description="The campaign's name; empty until one is given.")
    media_count: int = Field(description="Pictures and videos chosen.")
    age_min: int | None
    age_max: int | None
    genders: list[str] = Field(description="Ready to show: `Ayollar`, `Erkaklar`…")
    interests: list[str] = Field(description="The first few interests, by name.")
    interests_more: int = Field(description="How many more there are than shown.")
    adverts: list[LaunchChatCardAdvertOut] = Field(
        description="The first adverts' words."
    )


class SessionOut(BaseModel):
    session_id: uuid.UUID
    status: Literal["open", "ready", "closed"]
    lines: list[str] = Field(
        description="What the agent says now, before the question."
    )
    ask: LaunchChatAskOut | None = Field(
        description="The one question waiting; null when ready."
    )
    chips: list[LaunchChatChipOut]
    ready: bool
    stage: Literal[
        "asking", "media", "preparing", "review", "creating", "done", "failed"
    ] = Field(description="Where the advert stands, read off the launch itself.")
    wait: bool = Field(
        description="Ask again (GET) in a few seconds: work is going on."
    )
    card: LaunchChatCardOut | None = Field(
        description="What was prepared; only at `review`, otherwise null."
    )
    launch_id: uuid.UUID | None
    next: str = Field("", description="`media` while pictures are being chosen.")
    messages: list[LaunchChatMessageOut] = Field(
        description="The conversation, oldest first."
    )
    turns_left: int


def as_out(session: Any, out: Any, *, max_turns: int, next_step: str) -> SessionOut:
    from dataclasses import asdict

    said = out.reply
    return SessionOut(
        session_id=session.id,
        status=str(session.status),
        lines=list(said.lines),
        ask=LaunchChatAskOut(**asdict(said.ask)) if said.ask is not None else None,
        chips=[LaunchChatChipOut(**asdict(chip)) for chip in said.chips],
        ready=said.ready,
        stage=out.stage,
        wait=out.wait,
        card=LaunchChatCardOut(**out.card) if out.card else None,
        launch_id=session.launch_id,
        next=next_step if out.stage == next_step else "",
        messages=[LaunchChatMessageOut(**row) for row in session.messages or []],
        turns_left=max(0, max_turns - int(session.turns or 0)),
    )


__all__ = ["LaunchChatCardOut", "SessionOut", "TurnIn", "VoiceOut", "as_out"]
