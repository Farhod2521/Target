"""What a lead form shows after it is sent, in this product's own words."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlparse

EndingKind = Literal["none", "website", "telegram", "call"]

ENDING_NONE: Final = "none"
ENDING_WEBSITE: Final = "website"
ENDING_TELEGRAM: Final = "telegram"
ENDING_CALL: Final = "call"

ENDING_KINDS: Final[tuple[EndingKind, ...]] = (
    ENDING_NONE,
    ENDING_WEBSITE,
    ENDING_TELEGRAM,
    ENDING_CALL,
)

DEFAULT_BUTTON_TEXT: Final[Mapping[str, str]] = {
    ENDING_WEBSITE: "Saytga o'tish",
    ENDING_TELEGRAM: "Telegram'da yozish",
    ENDING_CALL: "Qo'ng'iroq qilish",
}

AI_ENDINGS: Final[Mapping[str, EndingKind]] = {
    "auto": ENDING_CALL,
    "beauty": ENDING_CALL,
    "construction": ENDING_CALL,
    "education": ENDING_CALL,
    "fitness": ENDING_CALL,
    "medical": ENDING_CALL,
    "real_estate": ENDING_CALL,
    "restaurant": ENDING_CALL,
    "services": ENDING_CALL,
    "ecommerce": ENDING_WEBSITE,
    "retail_store": ENDING_WEBSITE,
    "travel": ENDING_WEBSITE,
}

TELEGRAM_HOSTS: Final[frozenset[str]] = frozenset({"t.me", "telegram.me"})

_USERNAME: Final = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")


@dataclass(frozen=True, slots=True)
class FormEnding:
    """The screen after the form: its words, and the one button under them."""

    kind: EndingKind
    target: str = ""
    button_text: str = ""
    title: str = ""
    body: str = ""

    @property
    def has_button(self) -> bool:
        return self.kind != ENDING_NONE

    @property
    def words(self) -> str:
        """What the button says, the default when nothing was written."""
        if not self.has_button:
            return ""
        return self.button_text or DEFAULT_BUTTON_TEXT.get(self.kind, "")

    def as_answer(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "target": self.target,
            "button_text": self.button_text,
            "title": self.title,
            "body": self.body,
        }


def ending_from_answer(value: object) -> FormEnding | None:
    """A stored answer read back, or ``None`` for one that is not there."""
    if not isinstance(value, dict):
        return None
    kind = str(value.get("kind", ""))
    if kind not in ENDING_KINDS:
        return None
    return FormEnding(
        kind=kind,
        target=str(value.get("target", "")),
        button_text=str(value.get("button_text", "")),
        title=str(value.get("title", "")),
        body=str(value.get("body", "")),
    )


def telegram_username(raw: str) -> str:
    """The username in what somebody typed, or ``""`` if there is none."""
    text = raw.strip()
    if not text:
        return ""

    if "/" in text:
        address = text if "://" in text else f"https://{text}"
        parsed = urlparse(address)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host not in TELEGRAM_HOSTS:
            return ""
        text = parsed.path.strip("/").split("/")[0]

    text = text.removeprefix("@")
    return text if _USERNAME.fullmatch(text) else ""


def telegram_url(username: str) -> str:
    return f"https://t.me/{username}"


def telegram_of(url: str) -> str:
    """The username behind a Telegram address, or ``""`` for any other."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host not in TELEGRAM_HOSTS:
        return ""
    return telegram_username(url)


@dataclass(frozen=True, slots=True)
class EndingLine:
    """The button as one line on a card: what it says and where it goes."""

    words: str = ""
    target: str = ""


def line_of(ending: FormEnding) -> EndingLine:
    if not ending.has_button:
        return EndingLine()
    if ending.kind == ENDING_TELEGRAM:
        shown = f"@{ending.target}"
    elif ending.kind == ENDING_WEBSITE:
        shown = ending.target.split("://", 1)[-1].removeprefix("www.").rstrip("/")
    else:
        shown = ending.target
    return EndingLine(words=ending.words, target=shown)


def provider_line(*, kind: str, target: str, button_text: str) -> EndingLine | None:
    """A form's last screen as the provider described it, as the same line."""
    if kind == ENDING_NONE:
        return EndingLine()
    if kind == ENDING_WEBSITE:
        username = telegram_of(target)
        if username:
            ending = FormEnding(
                kind=ENDING_TELEGRAM, target=username, button_text=button_text
            )
        else:
            ending = FormEnding(
                kind=ENDING_WEBSITE, target=target, button_text=button_text
            )
        return line_of(ending)
    if kind == ENDING_CALL:
        return line_of(
            FormEnding(kind=ENDING_CALL, target=target, button_text=button_text)
        )
    if kind:
        return EndingLine(words=button_text)
    return None


def ai_ending_kind(*, category: str) -> EndingKind:
    """Which ending the rule picks for this category, before any data."""
    return AI_ENDINGS.get(category, ENDING_NONE)


__all__ = [
    "AI_ENDINGS",
    "DEFAULT_BUTTON_TEXT",
    "ENDING_CALL",
    "ENDING_KINDS",
    "ENDING_NONE",
    "ENDING_TELEGRAM",
    "ENDING_WEBSITE",
    "EndingKind",
    "EndingLine",
    "FormEnding",
    "ai_ending_kind",
    "ending_from_answer",
    "line_of",
    "provider_line",
    "telegram_of",
    "telegram_url",
    "telegram_username",
]
