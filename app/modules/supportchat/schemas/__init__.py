"""Response shapes for the client's support chat, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class FileOut(BaseModel):
    id: str
    kind: str = Field(description="`image`, `video`, `file` or `voice`.")
    name: str
    size: int = Field(description="Bytes.")
    seconds: int = Field(description="A voice message's length; 0 otherwise.")
    length: str = Field(description="`seconds` as m:ss.")
    url: str = Field(description="Download. Send the bearer header or `?token=`.")
    view_url: str = Field(
        description="Shown in the page (`?view=1`): pictures, video and voice "
        "answer with their type and a byte range; anything else downloads."
    )


class QuoteOut(BaseModel):
    id: str
    who: str
    text: str
    gone: bool = Field(description="The quoted message was taken back.")


class MessageOut(BaseModel):
    id: str
    side: str = Field(description="`client` or `office`: who wrote it.")
    own: bool = Field(description="The reader wrote it: drawn on the right.")
    who: str = Field(description="`Siz` or `Qo'llab-quvvatlash` for the client.")
    kind: str = Field(
        description="`text`, `image`, `video`, `file`, `voice` or `sticker`."
    )
    body: str
    sticker: str = Field(description="Sticker code; draw `stickers/<code>.svg`.")
    sticker_name: str
    sticker_emoji: str
    files: list[FileOut]
    quote: QuoteOut | None
    created_at: datetime
    at: int = Field(description="`created_at` in milliseconds.")
    edited_at: datetime | None
    deleted_at: datetime | None = Field(description="Set: draw `Xabar o'chirildi`.")
    editable: bool
    deletable: bool
    repliable: bool
    read: bool = Field(description="Own message the other side has read: two ticks.")
    preview: str = Field(description="The message in one line.")


class StickerOut(BaseModel):
    code: str
    emoji: str
    name: str


class ComposerOut(BaseModel):
    max_body_chars: int
    max_upload_mb: int
    max_send_mb: int
    max_files: int
    max_voice_seconds: int
    typing_beat_ms: int = Field(description='How often to send `{"typing": true}`.')
    typing_shown_ms: int = Field(description="How long to show the other side typing.")
    allowed_suffixes: list[str]
    voice_suffixes: list[str]
    stickers: list[StickerOut]


class ScreenOut(BaseModel):
    page_title: str
    viewer: str
    has_chat: bool = Field(description="False before the first message.")
    messages: list[MessageOut]
    page: int
    pages: int
    has_previous: bool
    has_next: bool
    cursor: str = Field(description="Pass to `GET /support/messages?after=`.")
    office_read_at: datetime | None
    send_key: str = Field(
        description="Send it back with the message: one press, one message."
    )
    ws_path: str = Field(description="The socket; add `?token=<access token>`.")
    composer: ComposerOut


class ChangesOut(BaseModel):
    cursor: str
    messages: list[MessageOut] = Field(
        description="New or changed since `after`; replace by `id`."
    )
    office_read_at: datetime | None


class SentOut(BaseModel):
    already_sent: bool = Field(description="A repeat of a press already stored.")
    message: MessageOut | None


class WidgetOut(BaseModel):
    has_chat: bool
    unread: bool = Field(description="The office wrote since the client last looked.")
    preview: str = Field(
        description="The office's newest message in a line, when unread."
    )
