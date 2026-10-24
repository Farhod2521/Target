"""Reading what Telegram posted, without a request object in sight.

Everything that decides whether to trust or act on an incoming update is a
pure function here - the rule ``metaads.webhooks`` is held to, and for the
same reason. A view that parses its own body is a view whose parsing can
only be tested through a view, and the interesting cases (a body that is
not what the docs promise, a secret that nearly matches) are exactly the
ones nobody writes a view test for.

**Four update types, everything else ignored.** A command, a button
press, something somebody typed - because this bot answers questions -
and a message with no words in it, so that a photograph is met with a
sentence rather than with silence. An ``edited_message`` handler is a
surface with no product behind it: a question is answered once, and
re-reading an edit would be a second answer to a message the reader can
no longer see the first of.
"""

import hmac
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

# Telegram's own ceiling on inline button data, in bytes. Checked when a
# keyboard is built rather than when it is sent: a button that is one byte
# over is refused by the API with a message about the whole request, and
# by then the number that was too long is three frames up the stack.
CALLBACK_DATA_MAX_BYTES: Final = 64

# What a command looks like. ``/start payload`` and ``/start@thebot
# payload`` are the same command - Telegram appends the username in group
# chats, and a bot that only matched the bare form would be silent there.
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
    # The message this one answers, when it was sent as a reply. Zero for
    # a message that quotes nothing. Carried because a reply is how a
    # person in Telegram says which of the bot's messages they mean.
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


Update = Command | ButtonPress | TextMessage | OtherMessage


def secret_matches(*, header: str, expected: str) -> bool:
    """Whether this delivery carries the secret ``setWebhook`` registered.

    Constant-time, like every other secret comparison in this codebase. An
    empty expected value is **never** a match: a deployment that has not
    configured a secret refuses everything rather than accepting whoever
    posts first, which is what ``META_WEBHOOK_VERIFY_TOKEN`` does with the
    same problem.
    """
    if not expected or not header:
        return False
    return hmac.compare_digest(header, expected)


def read_update(payload: dict[str, Any]) -> Update | None:
    """One posted body as something to act on, or nothing.

    ``None`` for every update this bot has no behaviour for, and that is
    the common case rather than an error: Telegram delivers whatever the
    subscription allows, and a channel post is not a malformed command.
    """
    press = _press(payload.get("callback_query"))
    if press is not None:
        return press
    message = payload.get("message")
    # A command first, because a command is also a message with text in
    # it, and anything with no words last. The order is the whole
    # distinction between the three readers.
    return _command(message) or _text(message) or _other(message)


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
    # ``/start@thebot`` in a group is the same command as ``/start``.
    name, _, _bot = head[1:].partition("@")
    if not name:
        return None

    return Command(
        chat_id=chat_id, sender=sender, name=name.lower(), argument=argument.strip()
    )


def _text(message: Any) -> TextMessage | None:
    """A message that carried words rather than an instruction.

    Everything without text is not this: a photograph, a voice note, a
    location, a sticker arrive as :class:`OtherMessage`, and a caption on
    a photograph is not read as a question - the words are usually about
    the picture, and an answer that could not see it would be a guess.
    """
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
    """A message somebody sent that carried no words, or nothing.

    Only a message a person sent: one with a sender and an id. Called
    after the two readers above, so anything that reaches here with text
    in it is something they already refused - a command addressed to
    nobody, say - and it is not a picture either.
    """
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
        # A press on a message too old for Telegram to send back. Nothing
        # can be edited and nothing identifies what was pressed on, so
        # there is no safe action - and answering the query is the
        # caller's business, not the parser's.
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
    """Telegram's own word for where this was said, or an empty string.

    Empty when the field is missing, which Telegram's documentation says
    cannot happen - so an empty value is a body that is not Telegram's,
    and a caller comparing it against "private" refuses it. That is the
    right direction to fail in: a bot that goes quiet is recoverable and a
    bot answering every message in somebody's group is not.
    """
    if not isinstance(chat, dict):
        return ""
    value = chat.get("type")
    return value if isinstance(value, str) else ""


def _chat_id(chat: Any) -> str:
    """Telegram's numeric chat id, as the string everything else stores.

    A string for the reason ``ExternalRef.id`` is one: it is an identifier
    rather than a quantity, nothing adds two of them, and a channel id is
    already a thirteen-digit negative number.
    """
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
    return Sender(id=str(value), username=str(user.get("username") or ""))


__all__ = [
    "CALLBACK_DATA_MAX_BYTES",
    "ButtonPress",
    "Command",
    "Sender",
    "TextMessage",
    "Update",
    "read_update",
    "secret_matches",
]
