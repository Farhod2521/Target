"""Bot API transport: the single place this product talks to Telegram.

Nine methods, and the list is the whole product surface: send a message,
send a picture or a file, edit one, answer a button press, register the
webhook, set the menu button, ask who we are, and ask what Telegram
thinks the webhook is. A bot that holds no conversation needs nothing
else.

The last of those is the only one no feature calls. It is here because the
failure this package can have - "nothing arrived" - leaves no trace on our
side at all: the update was never posted, so there is no log line to find
and no row to inspect. Telegram is the only party holding that fact.

**No retry loop.** Same rule as ``metaads.GraphClient``, and the callers in
this product decide against retrying every time: the three notifications
are each visible in the cabinet too, so a dropped message costs somebody a
ping and never a fact.

**No configuration read here.** The token and the base URL arrive as
arguments, like everywhere else in ``packages/`` - which is what lets this
be lifted into another project unchanged.
"""

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

# Deliberately short. Every call this package makes is on a path where
# something is waiting: a button press has about ten seconds before
# Telegram gives up on the answer, and a notification nobody gets is
# better than a worker slot held for a minute.
CONNECT_TIMEOUT_SECONDS: Final = 5.0
READ_TIMEOUT_SECONDS: Final = 10.0

# Telegram's own ceiling on message text, in UTF-16 code units. Ours is
# well under it - the longest message this product sends is a suggestion
# card, and Claude writes the sentence in the middle of one - so this is a
# guard rather than a budget, and text is cut rather than the send being
# refused: a truncated notification still says which screen to open, and a
# refused one says nothing at all.
#
# **Code units and not characters**, which is the ceiling Telegram counts
# in: an emoji is one character here and two units there, so a message
# measured with ``len`` can pass this and be refused by the API.
MESSAGE_MAX_CHARS: Final = 4_096

# The most buttons Telegram draws side by side. A longer shared row is
# wrapped onto the next line rather than refused: a scale from 0 to 10 is
# eleven answers to one question and still reads as one choice.
ROW_MAX_BUTTONS: Final = 8
ELLIPSIS: Final = "…"

# What a bot may upload, per Telegram: a picture sent as a photo up to ten
# megabytes, anything sent as a document up to fifty. The caller checks
# before reading the file - a refused upload is a whole file read for
# nothing - and sends a bigger one by name only.
PHOTO_MAX_BYTES: Final = 10 * 1024 * 1024
DOCUMENT_MAX_BYTES: Final = 50 * 1024 * 1024

# An upload is the one call here whose size the caller does not choose,
# and fifty megabytes do not leave in ten seconds.
UPLOAD_TIMEOUT_SECONDS: Final = 60.0


class BotClient:
    """One conversation with the Bot API.

    Holds the token because every call uses it and holds an ``httpx.Client``
    because a sweep sends several messages in a row. Both are the caller's
    to supply and the caller's to close.
    """

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

    # --- Methods ---------------------------------------------------------
    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        buttons: tuple[Button, ...] = (),
        preview: bool = False,
        reply_to: int = 0,
    ) -> SentMessage:
        """Post one message, optionally with a row of inline buttons.

        HTML rather than Markdown, and the caller escapes: Telegram's
        Markdown dialects treat an unescaped underscore in a campaign name
        as formatting and refuse the whole message for it, while HTML has
        exactly three characters to escape and a helper in the standard
        library. See ``apps.notifications.services.compose``.

        Link previews are off unless asked for. A notification that turns
        into a card of somebody's landing page is a notification whose own
        sentence has scrolled off the screen.

        ``reply_to`` quotes the message being answered. For a notification
        there is nothing to quote and it stays at zero; for an answer that
        took a model twenty seconds to write there may be three messages
        in between, and an answer to no visible question is a puzzle.
        ``allow_sending_without_reply`` so a quoted message somebody
        deleted costs the answer rather than only the quote.
        """
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
        """The "typing…" line, while something slow is happening.

        Telegram shows it for five seconds or until the next message,
        whichever comes first, so it is sent again rather than cancelled.
        Nothing is read back and a failure is not raised: this is a hint
        about a message that is coming, and losing the hint must never
        lose the message.
        """
        try:
            self._call("sendChatAction", {"chat_id": chat_id, "action": action})
        except TelegramError:
            # Deliberately swallowed, and the only place in this client
            # that swallows anything. Every other call is something the
            # caller has to know the outcome of.
            return

    def edit_message_text(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        buttons: tuple[Button, ...] = (),
    ) -> None:
        """Rewrite a message that is already on somebody's screen.

        With no ``buttons`` the keyboard goes: an empty ``reply_markup`` is
        how Telegram is told to remove one, and removing it is the point -
        a card whose buttons still offer a decision that has been made is a
        card that invites a second press.
        """
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
        """Change a message's buttons and leave its text where it is.

        For a message whose text must survive being acted on: an answer
        somebody asked for, with a button under it. Rewriting the whole
        message - which is how a card reports its own outcome - would take
        the answer off the screen and leave the reader holding the reply
        to a question they can no longer see.

        With no ``buttons`` the keyboard goes, which is the ordinary call
        here: the decision is made and there is nothing left to press.
        """
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
        """Stop the button spinning, and optionally say why.

        **Mandatory after every press.** Telegram leaves the button in a
        loading state until this arrives and gives up after about ten
        seconds, so a press that is silently handled looks broken even when
        it worked.

        ``alert`` is the modal box rather than the toast that fades. Used
        for refusals: a sentence explaining why nothing happened has to be
        dismissed rather than missed.
        """
        payload: dict[str, Any] = {"callback_query_id": query_id}
        if text:
            payload["text"] = text[:200]
        if alert:
            payload["show_alert"] = True
        self._call("answerCallbackQuery", payload)

    def set_webhook(self, *, url: str, secret_token: str) -> None:
        """Point Telegram at our endpoint, and at nothing else.

        ``allowed_updates`` is narrowed to what this bot acts on. Not an
        optimisation: an update type nobody handles is a body arriving at a
        public endpoint for no reason, and the shortest list is the one
        with the least to go wrong in it.
        """
        self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query"],
                # Anything queued while the webhook was unset is about a
                # cabinet state that has since moved on.
                "drop_pending_updates": True,
            },
        )

    def set_chat_menu_button(self, *, text: str, url: str) -> None:
        """Put a permanent Mini App button in the bot's menu, for everybody.

        No ``chat_id``, so this sets the default every conversation
        inherits. The per-chat form exists and is not used: a label chosen
        per reader would be one write to Telegram per person and one more
        thing to keep in step with a language somebody changed in the
        cabinet an hour ago.

        The same shape as :meth:`set_webhook` and run the same way - by
        hand, once, against the deployment somebody meant. It is a write to
        somebody else's system that changes what every user of this bot
        sees.
        """
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
        """What Telegram believes about our webhook, including its own errors.

        Reads nothing about this deployment and changes nothing on
        Telegram's side, which is what makes it safe to run against a
        production bot from a shell while somebody waits - unlike
        :meth:`set_webhook` next door, which redirects every update this
        bot has.
        """
        return WebhookInfo.model_validate(self._call("getWebhookInfo", {}))

    # --- Transport -------------------------------------------------------
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
        # ``getMe`` and ``sendMessage`` answer with an object; the rest
        # answer with a bare ``true``. Normalised so no caller has to
        # check the type of what it got.
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
    """The answers on one row, and anything that opens a page under them.

    A button asking for a row of its own gets one, under the shared row and
    above the pages - see :attr:`Button.row`. A shared row longer than
    Telegram draws is wrapped, :data:`ROW_MAX_BUTTONS` to a line.

    The split is about what a row means. Two buttons side by side read as
    a choice between them, and a card offering "Tasdiqlash · Rad etish ·
    Batafsil" invites somebody to read the third as a third answer. A page
    is not an answer, so it gets a line of its own - and on a narrow phone
    three long words in one row are truncated into each other anyway.
    """
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
    """The text, cut to something Telegram accepts as HTML.

    **A cut is not a slice, and that is the whole of this function.** Every
    message here is sent with ``parse_mode="HTML"``, so a cut that lands
    inside ``<a href="...">`` or leaves a ``<b>`` unclosed is not a shorter
    message - it is "can't parse entities" and no message at all, which is
    exactly the outcome the comment on :data:`MESSAGE_MAX_CHARS` says this
    exists to avoid. So the cut is taken at a boundary outside any tag and
    whatever is still open is closed after it.

    The tags are the caller's own - this package writes none - and the set
    it has to survive is whatever the caller writes. Tracking names rather
    than counting brackets is what makes that true of the next tag somebody
    adds.
    """
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
            # The cut lands in ordinary text, where any boundary is safe.
            cut = _prefix(text, room)
            if len(cut) >= index:
                return cut.rstrip() + ELLIPSIS + closers
            break

        kept, kept_closers = plain, closers
        if start == -1:
            break

        end = text.find(">", start)
        if end == -1:
            # A "<" that never closes. Telegram reads everything after it
            # as a tag, so nothing past it can be kept.
            break
        _track(stack, text[start + 1 : end])
        index = end + 1

    return text[:kept].rstrip() + ELLIPSIS + kept_closers


def _track(stack: list[str], inside: str) -> None:
    """What one tag does to the list of things still open.

    A close takes its own name and everything opened after it, which is
    what a browser and Telegram's parser both do with badly nested markup -
    guessing otherwise would leave a closer this function invented.
    """
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
    """How long Telegram thinks this is: UTF-16 code units.

    Anything outside the basic plane - an emoji in a campaign name - is one
    character to Python and two to the API.

    Public because a caller assembling a long message has to be able to ask
    before it sends one. This package cuts an over-long message rather than
    failing to send it, and a cut takes the tail - so a caller whose most
    valuable lines are at the end must measure and drop its own least
    valuable ones first. See :data:`MESSAGE_MAX_CHARS`.
    """
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
