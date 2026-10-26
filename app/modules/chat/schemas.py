"""Response shapes for the assistant's screen and weekly report, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.agent.selectors.cards import Card
from core.chat.report import WeeklyReport
from core.inbox.items import InboxItem


class FocusOut(BaseModel):
    card: Card | None = Field(
        description="The proposal this visit came from (`?suggestion=`)."
    )
    question: str = Field(description="A question to put in the box ready to send.")
    quote: dict[str, str] = Field(
        description="What the question is about, shown above it."
    )
    refusal: str = Field(description="Id of a refused launch to explain (`?launch=`).")
    item: InboxItem | None = Field(
        description="The waiting item this visit came from (`?item=`)."
    )


class ThreadOut(BaseModel):
    id: str
    title: str
    last_message_at: datetime | None
    created_at: datetime


class MessageOut(BaseModel):
    id: str
    role: str = Field(description="`user` or `assistant`.")
    text: str
    html: str = Field(description="`text` rendered from markdown.")
    status: str = Field(description="`pending`, `done` or `failed`.")
    masked_figures: int = Field(
        description="Figures hidden because they could not be checked."
    )
    quote: dict[str, str]
    offers: list[dict[str, str]] = Field(
        description="Proposals with a button; press with `POST /chat/choices/{pk}`."
    )
    changes: list[dict[str, str]] = Field(
        description="Changes the assistant prepared; confirm with "
        "`POST /chat/changes/{message_id}/{key}`."
    )
    replies: list[dict[str, str]] = Field(
        description="Ready follow-up questions to tap."
    )
    created_at: datetime


class ChatScreenOut(BaseModel):
    page_title: str
    entitled: bool = Field(description="False without a live plan: the box is closed.")
    focus: FocusOut
    waiting: int = Field(description="Proposals waiting for an answer.")
    sessions: list[ThreadOut] = Field(description="The thread rail, newest first.")
    thread: ThreadOut | None = Field(description="Only on `GET /chat/threads/{pk}`.")
    messages: list[MessageOut]
    choice_poll_seconds: int
    free_left: int = Field(description="Questions left today on the plan.")
    free_total: int = Field(description="The plan's daily questions.")


class CommentOut(BaseModel):
    text: str
    masked: int
    is_pending: bool = Field(description="Still being written: ask again with `try`.")
    advice: str


class ReportOut(BaseModel):
    entitled: bool
    report: WeeklyReport | None = Field(
        description="Null without a plan or a completed week. Also carries "
        "`silence` (why there is no sentence) and `wants_sentence` (bool)."
    )
    comment: CommentOut | None = None
    silence: str = Field("", description="The words shown in place of a sentence.")
    headline_label: str = ""
    next_try: int = Field(
        0, description="Ask again with `?try=` this value; 0 means stop asking."
    )


__all__ = ["ChatScreenOut", "ReportOut"]
