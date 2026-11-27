import uuid
from typing import Any

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


class OptionOut(BaseModel):
    label: str
    slot: str
    value: str
    recommended: bool = False
    opens: str = Field("", description="`form`: open the cabinet's lead form dialog.")


class AskOut(BaseModel):
    slot: str
    text: str
    options: list[OptionOut] = []
    input: str = Field(description="`text`, `url`, `phone`, `money` or `none`.")
    hint: str = ""


class ChipOut(BaseModel):
    slot: str
    label: str
    value: str


class MessageOut(BaseModel):
    author: str = Field(description="`user` or `agent`.")
    text: str
    at: str = ""


class VoiceOut(BaseModel):
    """A recording's words, for the message box - not sent as a message."""

    text: str
    language: str = ""


class SessionOut(BaseModel):
    session_id: uuid.UUID
    status: str = Field(description="`open`, `ready` or `closed`.")
    lines: list[str] = Field(
        description="What the agent says now, before the question."
    )
    ask: AskOut | None = Field(description="The one question waiting; null when ready.")
    chips: list[ChipOut]
    ready: bool
    stage: str = Field(
        description=(
            "`asking`, `media`, `preparing`, `review`, `creating`, `done` or `failed`."
        )
    )
    wait: bool = Field(
        description="Ask again (GET) in a few seconds: work is going on."
    )
    card: dict[str, Any] | None = Field(
        description="What was prepared, at `review`: audience, interests, adverts."
    )
    launch_id: uuid.UUID | None
    next: str = Field("", description="`media` while pictures are being chosen.")
    messages: list[MessageOut] = Field(description="The conversation, oldest first.")
    turns_left: int


def as_out(session: Any, out: Any, *, max_turns: int, next_step: str) -> SessionOut:
    from dataclasses import asdict

    said = out.reply
    return SessionOut(
        session_id=session.id,
        status=str(session.status),
        lines=list(said.lines),
        ask=AskOut(**asdict(said.ask)) if said.ask is not None else None,
        chips=[ChipOut(**asdict(chip)) for chip in said.chips],
        ready=said.ready,
        stage=out.stage,
        wait=out.wait,
        card=out.card,
        launch_id=session.launch_id,
        next=next_step if out.stage == next_step else "",
        messages=[MessageOut(**row) for row in session.messages or []],
        turns_left=max(0, max_turns - int(session.turns or 0)),
    )


__all__ = ["SessionOut", "TurnIn", "as_out"]
