"""Reading what Telegram posted, without a request object in sight."""

import hmac
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

CALLBACK_DATA_MAX_BYTES: Final = 64

_COMMAND_PREFIX: Final = "/"


class Sender(BaseModel):
    """Who sent it. The id is the only field anything decides on.

    ``username`` is carried for one screen - the cabinet saying which
    Telegram account is connected - and nothing else. It is not an
    identity: people change it, and two accounts can hold the same handle
    at different times.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    username: str = ""
    # First and last name as the person set them: a label for whoever reads
    # the chat on the other side, never something to decide on.
    name: str = ""


class Command(BaseModel):
    """A message that was a command, with whatever followed it.

    ``argument`` is the deep-link payload: Telegram delivers
    ``t.me/bot?start=XYZ`` as the message text ``/start XYZ``, which is
    the whole mechanism behind linking an account in two taps.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: Literal["command"] = "command"
    chat_id: str
    sender: Sender
    name: str
    argument: str = ""
    # As on :class:`TextMessage`: "private", "group", "supergroup".
    chat_type: str = ""


class TextMessage(BaseModel):
    """Something somebody typed that was not a command.

    ``message_id`` travels so the answer can be a reply to it. An answer
    takes as long as a model takes to write one - ten or twenty seconds -
    and by then the question may be several messages up the conversation.

    ``chat_type`` is Telegram's own word for where this was said -
    "private", "group", "supergroup", "channel" - and it is carried rather
    than acted on. A bot that answers every sentence is right in a private
    conversation and is a bot being removed from a group; which of those
    a deployment wants is not a question a parser should answer.

    The text is handed over as it arrived, trimmed and no more. What may
    be asked, how long it may be and what it costs are all decisions the
    caller makes; this package reads a body.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: Literal["text"] = "text"
    chat_id: str
    chat_type: str
    sender: Sender
    message_id: int
    text: str
    reply_to_message_id: int = 0


class OtherMessage(BaseModel):
    """A message with no words in it: a photograph, a voice note, a sticker.

    Carried so the caller can say something back - a person who sent one
    is waiting for an answer as much as one who typed. What it contained
    is not carried: nothing here can read a picture or a recording, and a
    field for it would be a promise that something does. ``chat_type``
    travels for the reason it does on :class:`TextMessage`.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: Literal["other"] = "other"
    chat_id: str
    chat_type: str
    sender: Sender
    message_id: int


class ButtonPress(BaseModel):
    """An inline button somebody tapped.

    ``query_id`` is what ``answerCallbackQuery`` needs and it expires in
    about ten seconds; ``message_id`` is what an edit needs and does not
    expire. Both travel on the press, which is why acting on one needs no
    stored state at all.

    ``sender`` is the account that pressed, and it is **not** necessarily
    the account the message was sent to: a forwarded message keeps its
    buttons. Checking the two match is the caller's job and the only
    authorisation this flow has.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: Literal["press"] = "press"
    chat_id: str
    sender: Sender
    query_id: str
    message_id: int
    data: str


class MediaMessage(BaseModel):
    """A message that carried a file: what it is and how to fetch it.

    Read by :func:`read_media`, not by :func:`read_update` - a bot that
    cannot keep a file goes on seeing an :class:`OtherMessage`, and only a
    caller that asks for the file gets the promise that it can have it.

    ``file_id`` is what ``getFile`` takes. ``kind`` is Telegram's own word:
    "photo", "document", "video", "voice", "audio", "video_note",
    "animation" or "sticker". A photo is its largest size. ``emoji`` is a
    sticker's own picture as a character; a sticker's file is not wanted.
    ``caption`` is the words under it, trimmed.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: str
    chat_id: str
    chat_type: str
    sender: Sender
    message_id: int
    file_id: str = ""
    file_name: str = ""
    mime: str = ""
    size: int = 0
    seconds: int = 0
    emoji: str = ""
    caption: str = ""
    reply_to_message_id: int = 0


class ChatMembership(BaseModel):
    """The bot itself was added to, changed in or removed from a chat.

    Telegram's ``my_chat_member``. ``sender`` is the person who did it -
    the one way to tell whose group or channel this is, since adding a
    bot to a channel carries no deep-link payload. ``status`` is
    Telegram's word for the bot's new place: "member", "administrator",
    "left", "kicked", "restricted". ``can_post`` is whether, as an
    administrator, it may post in a channel. ``restricted_may_send`` is a
    "restricted" bot that is still a member and may still send messages.
    ``public`` is a chat anybody can read by its handle.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: Literal["membership"] = "membership"
    chat_id: str
    chat_type: str
    title: str = ""
    public: bool = False
    sender: Sender
    status: str
    can_post: bool = False
    restricted_may_send: bool = False

    @property
    def present(self) -> bool:
        """In the chat and able to send there."""
        if self.status == "restricted":
            return self.restricted_may_send
        return self.status in ("member", "administrator", "creator")


Update = Command | ButtonPress | TextMessage | OtherMessage | ChatMembership

MEDIA_KINDS: Final = (
    "photo",
    "document",
    "video",
    "voice",
    "audio",
    "video_note",
    "animation",
    "sticker",
)


def secret_matches(*, header: str, expected: str) -> bool:
    """Whether this delivery carries the secret ``setWebhook`` registered."""
    if not expected or not header:
        return False
    return hmac.compare_digest(header, expected)


def read_update(payload: dict[str, Any]) -> Update | None:
    """One posted body as something to act on, or nothing."""
    press = _press(payload.get("callback_query"))
    if press is not None:
        return press
    membership = _membership(payload.get("my_chat_member"))
    if membership is not None:
        return membership
    message = payload.get("message")
    return _command(message) or _text(message) or _other(message)


def read_media(payload: dict[str, Any]) -> MediaMessage | None:
    """The file one posted message carried, or nothing - a text, a command,
    a press, or a kind of message this does not know."""
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    chat_id = _chat_id(chat)
    sender = _sender(message.get("from"))
    message_id = message.get("message_id")
    if not chat_id or sender is None or not isinstance(message_id, int):
        return None
    for kind in MEDIA_KINDS:
        found = message.get(kind)
        # "animation" also arrives as "document"; its own key comes first.
        if kind == "document" and isinstance(message.get("animation"), dict):
            continue
        body = (
            found[-1]
            if kind == "photo" and isinstance(found, list) and found
            else found
        )
        if not isinstance(body, dict) or not body.get("file_id"):
            continue
        return MediaMessage(
            kind=kind,
            chat_id=chat_id,
            chat_type=_chat_type(chat),
            sender=sender,
            message_id=message_id,
            file_id=str(body.get("file_id") or ""),
            file_name=str(body.get("file_name") or ""),
            mime=str(body.get("mime_type") or ""),
            size=_int(body.get("file_size")),
            seconds=_int(body.get("duration")),
            emoji=str(body.get("emoji") or "") if kind == "sticker" else "",
            caption=str(message.get("caption") or "").strip(),
            reply_to_message_id=_replied_id(message.get("reply_to_message")),
        )
    return None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _command(message: Any) -> Command | None:
    """A message, if it was a command addressed to this bot."""
    if not isinstance(message, dict):
        return None

    chat_id = _chat_id(message.get("chat"))
    sender = _sender(message.get("from"))
    text = str(message.get("text") or "").strip()
    if not chat_id or sender is None or not text.startswith(_COMMAND_PREFIX):
        return None

    head, _, argument = text.partition(" ")
    name, _, _bot = head[1:].partition("@")
    if not name:
        return None

    return Command(
        chat_id=chat_id,
        sender=sender,
        name=name.lower(),
        argument=argument.strip(),
        chat_type=_chat_type(message.get("chat")),
    )


def _membership(change: Any) -> ChatMembership | None:
    """The bot's own place in a chat, as it is now, or nothing."""
    if not isinstance(change, dict):
        return None
    chat = change.get("chat")
    chat_id = _chat_id(chat)
    sender = _sender(change.get("from"))
    member = change.get("new_chat_member")
    if not chat_id or sender is None or not isinstance(member, dict):
        return None
    status = str(member.get("status") or "")
    if not status:
        return None
    return ChatMembership(
        chat_id=chat_id,
        chat_type=_chat_type(chat),
        title=str(chat.get("title") or "") if isinstance(chat, dict) else "",
        public=bool(chat.get("username")) if isinstance(chat, dict) else False,
        sender=sender,
        status=status,
        can_post=status == "creator" or bool(member.get("can_post_messages")),
        restricted_may_send=status == "restricted"
        and bool(member.get("is_member"))
        and bool(member.get("can_send_messages")),
    )


def _text(message: Any) -> TextMessage | None:
    """A message that carried words rather than an instruction."""
    if not isinstance(message, dict):
        return None

    chat = message.get("chat")
    chat_id = _chat_id(chat)
    sender = _sender(message.get("from"))
    text = str(message.get("text") or "").strip()
    message_id = message.get("message_id")
    if not chat_id or sender is None or not text or not isinstance(message_id, int):
        return None

    return TextMessage(
        chat_id=chat_id,
        chat_type=_chat_type(chat),
        sender=sender,
        message_id=message_id,
        text=text,
        reply_to_message_id=_replied_id(message.get("reply_to_message")),
    )


def _other(message: Any) -> OtherMessage | None:
    """A message somebody sent that carried no words, or nothing."""
    if not isinstance(message, dict) or str(message.get("text") or "").strip():
        return None

    chat = message.get("chat")
    chat_id = _chat_id(chat)
    sender = _sender(message.get("from"))
    message_id = message.get("message_id")
    if not chat_id or sender is None or not isinstance(message_id, int):
        return None

    return OtherMessage(
        chat_id=chat_id,
        chat_type=_chat_type(chat),
        sender=sender,
        message_id=message_id,
    )


def _replied_id(replied: Any) -> int:
    """The id of the message this one replies to, or zero."""
    if not isinstance(replied, dict):
        return 0
    value = replied.get("message_id")
    return value if isinstance(value, int) else 0


def _press(query: Any) -> ButtonPress | None:
    """A button press, if the body carried one that names its message."""
    if not isinstance(query, dict):
        return None

    message = query.get("message")
    if not isinstance(message, dict):
        return None

    chat_id = _chat_id(message.get("chat"))
    sender = _sender(query.get("from"))
    query_id = str(query.get("id") or "")
    message_id = message.get("message_id")
    data = str(query.get("data") or "")

    if not (chat_id and sender and query_id and data) or not isinstance(
        message_id, int
    ):
        return None

    return ButtonPress(
        chat_id=chat_id,
        sender=sender,
        query_id=query_id,
        message_id=message_id,
        data=data,
    )


def _chat_type(chat: Any) -> str:
    """Telegram's own word for where this was said, or an empty string."""
    if not isinstance(chat, dict):
        return ""
    value = chat.get("type")
    return value if isinstance(value, str) else ""


def _chat_id(chat: Any) -> str:
    """Telegram's numeric chat id, as the string everything else stores."""
    if not isinstance(chat, dict):
        return ""
    value = chat.get("id")
    return str(value) if isinstance(value, int) else ""


def _sender(user: Any) -> Sender | None:
    if not isinstance(user, dict):
        return None
    value = user.get("id")
    if not isinstance(value, int):
        return None
    name = " ".join(
        part
        for part in (
            str(user.get("first_name") or ""),
            str(user.get("last_name") or ""),
        )
        if part.strip()
    )
    return Sender(
        id=str(value), username=str(user.get("username") or ""), name=name.strip()
    )


__all__ = [
    "CALLBACK_DATA_MAX_BYTES",
    "MEDIA_KINDS",
    "ButtonPress",
    "ChatMembership",
    "Command",
    "MediaMessage",
    "Sender",
    "TextMessage",
    "Update",
    "read_media",
    "read_update",
    "secret_matches",
]
