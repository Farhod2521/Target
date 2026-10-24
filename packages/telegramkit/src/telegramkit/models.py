"""What goes into a message and what comes back from one."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from telegramkit.updates import CALLBACK_DATA_MAX_BYTES


class Button(BaseModel):
    """One inline button: what it says, and what happens when it is pressed.

    Two kinds, and exactly one of them per button. ``data`` comes back to
    the webhook as a press; ``web_app`` opens a page inside Telegram and
    sends nothing. A button with both would be a keyboard Telegram refuses
    and a button with neither would be one nobody can use, so both are
    caught here rather than in an API error about the whole request.

    ``data`` is checked for length in the same place and for the same
    reason: Telegram rejects an over-long value with a message that names
    none of the buttons, so by the time the error arrives the value that
    was too long is several frames away.

    **``web_app`` works in private chats only.** That is Telegram's rule,
    not ours, and this product has no other kind of conversation - but it
    is why a group chat would silently lose these buttons.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    data: str = ""
    web_app: str = ""
    row: Literal["shared", "own"] = "shared"
    style: Literal["success", "danger", "primary"] | None = None

    def as_payload(self) -> dict[str, Any]:
        if bool(self.data) == bool(self.web_app):
            raise ValueError(
                f"a button carries either callback data or a web_app url, "
                f"not both and not neither: {self.text!r}"
            )
        styled: dict[str, Any] = {"style": self.style} if self.style else {}
        if self.web_app:
            return {"text": self.text, "web_app": {"url": self.web_app}, **styled}
        if len(self.data.encode("utf-8")) > CALLBACK_DATA_MAX_BYTES:
            raise ValueError(
                f"callback data is over {CALLBACK_DATA_MAX_BYTES} bytes: {self.data!r}"
            )
        return {"text": self.text, "callback_data": self.data, **styled}

    @property
    def opens_a_page(self) -> bool:
        """Whether this button leads somewhere rather than answering something."""
        return bool(self.web_app)


class SentMessage(BaseModel):
    """What came back from a send: the id an edit would need."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    message_id: int = 0
    chat_id: str = ""


class BotIdentity(BaseModel):
    """Who the token belongs to. Read once, by the webhook command."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    username: str


class WebhookInfo(BaseModel):
    """Telegram's own account of the webhook, for when nothing is arriving.

    The one shape in this package that exists purely to be read by a
    person. "No message came" has four causes that look identical from
    this side - no webhook registered, one registered somewhere else, one
    registered here and refused, or one accepted and stuck behind a
    worker - and every one of them is named in these five fields.

    ``last_error_message`` is Telegram quoting our own endpoint back at
    us: a mismatched secret arrives here as "Wrong response from the
    webhook: 403 Forbidden", which is the answer that would otherwise
    take a server, a log and a guess to reach.

    **The secret is not in it, and cannot be.** Telegram never returns
    what was registered, so a secret changed after ``setWebhook`` is
    visible only as that 403 - which is why the error field is carried
    rather than summarised into a boolean.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    url: str = ""
    pending_update_count: int = 0
    last_error_date: int = 0
    last_error_message: str = ""
    allowed_updates: tuple[str, ...] = ()


__all__ = ["BotIdentity", "Button", "SentMessage", "WebhookInfo"]
