"""Bot API transport: the single place this product talks to Telegram."""

import json
from types import TracebackType
from typing import Any, Final, Self

import httpx

from telegramkit.errors import (
    TelegramAPIError,
    TelegramError,
    TelegramTemporaryError,
    scrubbed,
    translate,
)
from telegramkit.models import BotIdentity, Button, SentMessage, WebhookInfo

API_BASE_URL: Final = "https://api.telegram.org"

CONNECT_TIMEOUT_SECONDS: Final = 5.0
READ_TIMEOUT_SECONDS: Final = 10.0

MESSAGE_MAX_CHARS: Final = 4_096

ROW_MAX_BUTTONS: Final = 8
ELLIPSIS: Final = "…"

PHOTO_MAX_BYTES: Final = 10 * 1024 * 1024
DOCUMENT_MAX_BYTES: Final = 50 * 1024 * 1024

UPLOAD_TIMEOUT_SECONDS: Final = 60.0


class BotClient:
    """One conversation with the Bot API."""

    def __init__(
        self,
        *,
        token: str,
        base_url: str = API_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        if not token:
            raise ValueError("a bot token is required")
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
                write=READ_TIMEOUT_SECONDS,
                pool=CONNECT_TIMEOUT_SECONDS,
            )
        )
        self._owns_client = client is None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Only closes what it opened. A borrowed client stays open."""
        if self._owns_client:
            self._client.close()

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        buttons: tuple[Button, ...] = (),
        preview: bool = False,
        reply_to: int = 0,
    ) -> SentMessage:
        """Post one message, optionally with a row of inline buttons."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": _fits(text),
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": not preview},
        }
        if buttons:
            payload["reply_markup"] = _keyboard(buttons)
        if reply_to:
            payload["reply_parameters"] = {
                "message_id": reply_to,
                "allow_sending_without_reply": True,
            }

        answer = self._call("sendMessage", payload)
        return SentMessage(
            message_id=int(answer.get("message_id") or 0),
            chat_id=str((answer.get("chat") or {}).get("id") or chat_id),
        )

    def send_photo(
        self, *, chat_id: str, filename: str, content: bytes, reply_to: int = 0
    ) -> SentMessage:
        """Post a picture, drawn in the chat rather than offered as a file.
        Telegram recompresses it; :meth:`send_document` keeps the bytes."""
        return self._upload(
            "sendPhoto",
            field="photo",
            chat_id=chat_id,
            filename=filename,
            content=content,
            reply_to=reply_to,
        )

    def send_document(
        self, *, chat_id: str, filename: str, content: bytes, reply_to: int = 0
    ) -> SentMessage:
        """Post any file as it is, under its own name."""
        return self._upload(
            "sendDocument",
            field="document",
            chat_id=chat_id,
            filename=filename,
            content=content,
            reply_to=reply_to,
        )

    def send_chat_action(self, *, chat_id: str, action: str = "typing") -> None:
        """The "typing…" line, while something slow is happening."""
        try:
            self._call("sendChatAction", {"chat_id": chat_id, "action": action})
        except TelegramError:
            return

    def edit_message_text(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        buttons: tuple[Button, ...] = (),
    ) -> None:
        """Rewrite a message that is already on somebody's screen."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": _fits(text),
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "reply_markup": _keyboard(buttons),
        }
        self._call("editMessageText", payload)

    def edit_message_buttons(
        self, *, chat_id: str, message_id: int, buttons: tuple[Button, ...] = ()
    ) -> None:
        """Change a message's buttons and leave its text where it is."""
        self._call(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": _keyboard(buttons),
            },
        )

    def answer_callback_query(
        self, *, query_id: str, text: str = "", alert: bool = False
    ) -> None:
        """Stop the button spinning, and optionally say why."""
        payload: dict[str, Any] = {"callback_query_id": query_id}
        if text:
            payload["text"] = text[:200]
        if alert:
            payload["show_alert"] = True
        self._call("answerCallbackQuery", payload)

    def set_webhook(self, *, url: str, secret_token: str) -> None:
        """Point Telegram at our endpoint, and at nothing else."""
        self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": True,
            },
        )

    def set_chat_menu_button(self, *, text: str, url: str) -> None:
        """Put a permanent Mini App button in the bot's menu, for everybody."""
        self._call(
            "setChatMenuButton",
            {"menu_button": {"type": "web_app", "text": text, "web_app": {"url": url}}},
        )

    def get_me(self) -> BotIdentity:
        """Who this token is. The one call that reads rather than writes."""
        answer = self._call("getMe", {})
        return BotIdentity(
            id=str(answer.get("id") or ""), username=str(answer.get("username") or "")
        )

    def get_webhook_info(self) -> WebhookInfo:
        """What Telegram believes about our webhook, including its own errors."""
        return WebhookInfo.model_validate(self._call("getWebhookInfo", {}))

    def _upload(
        self,
        method: str,
        *,
        field: str,
        chat_id: str,
        filename: str,
        content: bytes,
        reply_to: int,
    ) -> SentMessage:
        """One multipart POST. Form fields are strings, so the reply's
        parameters travel as JSON text."""
        data: dict[str, str] = {"chat_id": chat_id}
        if reply_to:
            data["reply_parameters"] = json.dumps(
                {"message_id": reply_to, "allow_sending_without_reply": True}
            )
        answer = self._post(
            method,
            data=data,
            files={field: (filename, content)},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
        return SentMessage(
            message_id=int(answer.get("message_id") or 0),
            chat_id=str((answer.get("chat") or {}).get("id") or chat_id),
        )

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """One JSON POST."""
        return self._post(method, json=payload)

    def _post(self, method: str, **request: Any) -> dict[str, Any]:
        """One POST, with the failure translated into something to catch.
        ``request`` is httpx's own keywords - the body and, for an upload,
        a longer timeout."""
        url = f"{self._base_url}/bot{self._token}/{method}"
        try:
            response = self._client.post(url, **request)
        except httpx.TimeoutException as exc:
            raise TelegramTemporaryError(
                f"Telegram did not answer in time: {exc}"
            ) from exc
        except httpx.TransportError as exc:
            raise TelegramTemporaryError(f"could not reach Telegram: {exc}") from exc

        body = _decode(response)
        if response.status_code >= 400 or not body.get("ok"):
            raise translate(status=response.status_code, payload=body)

        result = body.get("result")
        return result if isinstance(result, dict) else {}


def _decode(response: httpx.Response) -> dict[str, Any]:
    """The body as a dict. A non-JSON answer is Telegram, not us."""
    try:
        payload = response.json()
    except ValueError:
        raise TelegramTemporaryError(
            f"Telegram returned a non-JSON body ({response.status_code}): "
            f"{scrubbed(response.text[:200])}"
        ) from None
    if not isinstance(payload, dict):
        raise TelegramAPIError(f"unexpected body ({response.status_code})")
    return payload


def _keyboard(buttons: tuple[Button, ...]) -> dict[str, Any]:
    """The answers on one row, and anything that opens a page under them."""
    answers = [
        button.as_payload()
        for button in buttons
        if not button.opens_a_page and button.row == "shared"
    ]
    alone = [
        [button.as_payload()]
        for button in buttons
        if not button.opens_a_page and button.row == "own"
    ]
    pages = [[button.as_payload()] for button in buttons if button.opens_a_page]
    shared = [
        answers[start : start + ROW_MAX_BUTTONS]
        for start in range(0, len(answers), ROW_MAX_BUTTONS)
    ]
    rows = shared + alone + pages
    return {"inline_keyboard": rows}


def _fits(text: str) -> str:
    """The text, cut to something Telegram accepts as HTML."""
    if _units(text) <= MESSAGE_MAX_CHARS:
        return text
    return _cut(text)


def _cut(text: str) -> str:
    """The longest prefix that is still valid HTML, plus what closes it."""
    limit = MESSAGE_MAX_CHARS - _units(ELLIPSIS)
    stack: list[str] = []
    kept, kept_closers = 0, ""
    index = 0

    while True:
        closers = "".join(f"</{name}>" for name in reversed(stack))
        room = limit - _units(closers)

        start = text.find("<", index)
        plain = len(text) if start == -1 else start
        if _units(text[:plain]) > room:
            cut = _prefix(text, room)
            if len(cut) >= index:
                return cut.rstrip() + ELLIPSIS + closers
            break

        kept, kept_closers = plain, closers
        if start == -1:
            break

        end = text.find(">", start)
        if end == -1:
            break
        _track(stack, text[start + 1 : end])
        index = end + 1

    return text[:kept].rstrip() + ELLIPSIS + kept_closers


def _track(stack: list[str], inside: str) -> None:
    """What one tag does to the list of things still open."""
    tag = inside.strip()
    if not tag or tag.startswith("!") or tag.endswith("/"):
        return
    if tag.startswith("/"):
        name = tag[1:].strip().lower()
        if name in stack:
            del stack[stack.index(name) :]
        return
    stack.append(tag.split(maxsplit=1)[0].lower())


def message_units(text: str) -> int:
    """How long Telegram thinks this is: UTF-16 code units."""
    return len(text) + sum(1 for char in text if char > "\uffff")


_units = message_units


def _prefix(text: str, units: int) -> str:
    """The longest prefix that fits in ``units``, never splitting a pair."""
    used = 0
    for index, char in enumerate(text):
        cost = 2 if char > "\uffff" else 1
        if used + cost > units:
            return text[:index]
        used += cost
    return text


__all__ = [
    "API_BASE_URL",
    "MESSAGE_MAX_CHARS",
    "BotClient",
    "BotIdentity",
    "Button",
    "SentMessage",
    "WebhookInfo",
]
