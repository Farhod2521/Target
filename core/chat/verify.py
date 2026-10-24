"""The gate a figure has to pass before it reaches the screen."""

import re
from dataclasses import dataclass, field
from typing import Final

from core.chat.numbers import FIGURE, GAPS, canonical

MARKER: Final = "[?]"

GENERIC_BELOW: Final = 100

BARE_BELOW: Final = 11

CLAIM: Final = re.compile(rf"({FIGURE.pattern})(%)?")

_APOSTROPHE: Final = "['\u02bb\u2019`]"
_LETTER: Final = rf"(?:[^\W\d_]|{_APOSTROPHE})"

_RUSSIAN: Final = (
    "сум|сўм|руб|долл|евро|"  # noqa: RUF001 - Russian, not look-alikes
    "заяв|лид|диалог|звон|клик|переход|показ|процент"
)

_SCALE: Final = (
    "ming|million|milliard|mln|mlrd|thousand|billion|тыс|миллион|миллиард|млн|млрд"
)

CLAIMED_BY: Final = re.compile(
    rf"\s?(?:ta\s+)?(?:%|usd|uzs|eur|rub|kzt|dollar|euro|evro|so{_APOSTROPHE}m|"
    rf"(?:som|sum)(?:\b|ga\b|dan\b|lik)|"
    rf"murojaat|lid\b|lead|suhbat|conversation|qo{_APOSTROPHE}?ng{_APOSTROPHE}?iroq|"
    rf"call|bosish|click|o{_APOSTROPHE}?tish|visit|ko{_APOSTROPHE}?rish|marta|"
    rf"times|foiz|percent|barobar|baravar|{_SCALE}|{_RUSSIAN})",
    re.IGNORECASE,
)
MONEY_BEFORE: Final = re.compile(r"[$€₽]\s?$")

PEOPLE: Final = re.compile(
    rf"\s?(?:(?:{_SCALE})\s+)?(?:kishi|odam|people|persons?|человек)",
    re.IGNORECASE,
)

_RUSSIAN_TIME: Final = "лет|год|км|дн|день|час|мин|сек|недел|месяц"
QUANTITY: Final = re.compile(
    rf"\s?(?:[-\u2013\u2014]\s?\d+\s?)?(?:yosh|years?|km|kun|days?|soat|hours?|daqiqa|"
    rf"minutes?|soniya|sekund|seconds?|hafta|weeks?|oy\b|months?|{_RUSSIAN_TIME})",
    re.IGNORECASE,
)

RATIOS: Final = frozenset({"9:16", "16:9", "1:1", "4:5", "4:3", "3:4"})
RATIO: Final = re.compile(r"(?<!\d)\d{1,2}:\d{1,2}(?!\d)")

_OPENING: Final = r"\d{1,2}:|\d+\s?[-\u2013\u2014]\s?"
HELD: Final = re.compile(
    rf"(?:{_OPENING})?\d[\d{GAPS},.]*(?:[{GAPS}]?(?:ta[{GAPS}]+)?{_LETTER}{{0,14}}%?)?$"
    rf"|(?:{_OPENING})$"
)


@dataclass(slots=True)
class FigureGate:
    """Passes text through, holding every figure up to the light."""

    allowed: frozenset[str]
    quoted: frozenset[str] = frozenset()
    marker: str = MARKER
    generic_below: int = GENERIC_BELOW
    people_below: int = 0
    masked: int = 0
    _tail: str = field(default="", repr=False)

    def feed(self, text: str) -> str:
        """The part of ``text`` that is safe to show now."""
        buffer = self._tail + text
        unfinished = HELD.search(buffer)
        if unfinished is None:
            self._tail = ""
            return self._judge(buffer)

        self._tail = buffer[unfinished.start() :]
        return self._judge(buffer[: unfinished.start()])

    def allow(self, figures: frozenset[str]) -> None:
        """Let these figures through from now on."""
        self.allowed = self.allowed | figures

    def flush(self) -> str:
        """Whatever was still being held, now that nothing more is coming."""
        held, self._tail = self._tail, ""
        return self._judge(held)

    def _judge(self, text: str) -> str:
        return CLAIM.sub(self._decide, text)

    def _decide(self, match: re.Match[str]) -> str:
        digits = canonical(match.group(1))
        is_share = match.group(2) is not None

        if digits in self.allowed or digits in self.quoted:
            return match.group(0)
        if _in_ratio(match):
            return match.group(0)
        if not is_share and digits and self._is_language(match, int(digits)):
            return match.group(0)

        self.masked += 1
        return self.marker

    def _is_language(self, match: re.Match[str], value: int) -> bool:
        """Whether a figure nobody supplied is a word of the sentence."""
        after = match.string[match.end() :]
        before = match.string[: match.start()]
        if value < self.people_below and PEOPLE.match(after):
            return True
        if CLAIMED_BY.match(after) or MONEY_BEFORE.search(before):
            return False
        if value < self.generic_below and QUANTITY.match(after):
            return True
        return value < BARE_BELOW


def _in_ratio(match: re.Match[str]) -> bool:
    """Whether the figure is one side of a screen shape like 9:16."""
    return any(
        found.start() <= match.start() < found.end() and found.group(0) in RATIOS
        for found in RATIO.finditer(match.string)
    )
