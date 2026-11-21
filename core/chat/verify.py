"""The gate a figure has to pass before it reaches the screen."""

import re
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final

from core.chat.numbers import FIGURE, GAPS, canonical

MARKER: Final = "[?]"

GENERIC_BELOW: Final = 100

BARE_BELOW: Final = 11

CLAIM: Final = re.compile(rf"({FIGURE.pattern})(%)?")

_APOSTROPHE: Final = "['\u02bb\u2019`]"
_LETTER: Final = rf"(?:[^\W\d_]|{_APOSTROPHE})"

_RUSSIAN: Final = (
    "сум|сўм|руб|долл|евро|заяв|лид|диалог|звон|клик|переход|показ|процент"
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

# A day of the month, written with the month's name: "21-noyabr", "21 ноября",
# "21-23 noyabr". Each entry starts a month's name in Uzbek, Russian or English.
_MONTHS: Final[tuple[tuple[str, ...], ...]] = (
    ("yanvar", "январ", "january"),
    ("fevral", "феврал", "february"),
    ("mart", "март", "march"),
    ("aprel", "апрел", "april"),
    ("may", "май", "мая"),
    ("iyun", "июн", "june"),
    ("iyul", "июл", "july"),
    ("avgust", "август", "august"),
    ("sentabr", "sentyabr", "сентябр", "september"),
    ("oktabr", "oktyabr", "октябр", "october"),
    ("noyabr", "ноябр", "november"),
    ("dekabr", "декабр", "december"),
)
_MONTH_OF: Final[dict[str, int]] = {
    name: number for number, names in enumerate(_MONTHS, 1) for name in names
}
_DASH: Final = "[-\u2013\u2014]"
MONTH_AFTER: Final = re.compile(
    rf"(?:\s?{_DASH}\s?\d{{1,2}})?\s?{_DASH}?\s?"
    rf"({'|'.join(sorted(_MONTH_OF, key=len, reverse=True))})",
    re.IGNORECASE,
)
# A date as the look-ups write it: 21.11.2026, 21.11, 2026-11-21.
_DOTTED: Final = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?:\.\d{4})?(?![\d])")
_ISO: Final = re.compile(r"(?<!\d)\d{4}-(\d{2})-(\d{2})(?!\d)")

# "12,45 mln": a figure cut short by a word for its size.
_SIZES: Final[tuple[tuple[str, int], ...]] = (
    ("ming|thousand|тыс", 10**3),
    ("million|mln|миллион|млн", 10**6),
    ("milliard|mlrd|billion|миллиард|млрд", 10**9),
)
SIZE_AFTER: Final = tuple(
    (re.compile(rf"\s?(?:{words})", re.IGNORECASE), size) for words, size in _SIZES
)
# "11. Ali": the number of a row in a list, at the start of its line.
ORDINAL_AFTER: Final = re.compile(r"[.)]\s")

RATIOS: Final = frozenset({"9:16", "16:9", "1:1", "4:5", "4:3", "3:4"})
RATIO: Final = re.compile(r"(?<!\d)\d{1,2}:\d{1,2}(?!\d)")

_OPENING: Final = r"\d{1,2}:|\d+\s?[-\u2013\u2014]\s?"
HELD: Final = re.compile(
    rf"(?:{_OPENING})?\d[\d{GAPS},.]*(?:[{GAPS}]?(?:ta[{GAPS}]+)?{_LETTER}{{0,14}}%?)?$"
    rf"|(?:{_OPENING})$"
    rf"|\d{{1,2}}\s?{_DASH}\s?{_LETTER}{{0,14}}$"
)


def dates_in(text: str) -> frozenset[tuple[int, int]]:
    """Every (day, month) a text names as 21.11.2026, 21.11 or 2026-11-21."""
    found = {(int(d), int(m)) for d, m in _DOTTED.findall(text)}
    found |= {(int(d), int(m)) for m, d in _ISO.findall(text)}
    return frozenset((d, m) for d, m in found if 1 <= d <= 31 and 1 <= m <= 12)


@dataclass(slots=True)
class FigureGate:
    """Passes text through, holding every figure up to the light."""

    allowed: frozenset[str]
    quoted: frozenset[str] = frozenset()
    marker: str = MARKER
    generic_below: int = GENERIC_BELOW
    people_below: int = 0
    # Row numbers of a list below this pass at the start of a line; 0: none.
    ordinals_below: int = 0
    # The (day, month) pairs that may be written with the month's name.
    dates: frozenset[tuple[int, int]] = frozenset()
    masked: int = 0
    _tail: str = field(default="", repr=False)
    _line_start: bool = field(default=True, repr=False)

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

    def allow_dates(self, dates: frozenset[tuple[int, int]]) -> None:
        """Let these days be written with their month's name."""
        self.dates = self.dates | dates

    def flush(self) -> str:
        """Whatever was still being held, now that nothing more is coming."""
        held, self._tail = self._tail, ""
        return self._judge(held)

    def _judge(self, text: str) -> str:
        judged = CLAIM.sub(self._decide, text)
        if "\n" in text:
            self._line_start = not text.rsplit("\n", 1)[1].strip(" \t")
        elif text.strip(" \t"):
            self._line_start = False
        return judged

    def _decide(self, match: re.Match[str]) -> str:
        digits = canonical(match.group(1))
        is_share = match.group(2) is not None

        if digits in self.allowed or digits in self.quoted:
            return match.group(0)
        if _in_ratio(match):
            return match.group(0)
        if not is_share and self._is_known(match):
            return match.group(0)
        if not is_share and digits and self._is_language(match, int(digits)):
            return match.group(0)

        self.masked += 1
        return self.marker

    def _is_known(self, match: re.Match[str]) -> bool:
        """Whether the figure is one a look-up gave, written another way: a
        day by its month's name, an amount cut short, a row's number."""
        token = match.group(1)
        after = match.string[match.end() :]
        before = match.string[: match.start()]
        if token.isdigit() and len(token) <= 2:
            month = MONTH_AFTER.match(after)
            if month and (int(token), _MONTH_OF[month.group(1).lower()]) in self.dates:
                return True
        if (
            token.isdigit()
            and int(token) < self.ordinals_below
            and ORDINAL_AFTER.match(after)
            and self._starts_line(before)
        ):
            return True
        return self._is_short_for(token, after)

    def _starts_line(self, before: str) -> bool:
        if "\n" in before:
            return not before.rsplit("\n", 1)[1].strip(" \t")
        return self._line_start and not before.strip(" \t")

    def _is_short_for(self, token: str, after: str) -> bool:
        """ "12,45 mln" when a look-up gave 12 450 000: the same amount,
        rounded or cut to the places written."""
        size = next((size for word, size in SIZE_AFTER if word.match(after)), 0)
        if not size:
            return False
        plain = "".join(ch for ch in token if ch not in GAPS).replace(",", ".")
        try:
            value = Decimal(plain)
        except InvalidOperation:
            return False
        places = value.as_tuple().exponent
        if not isinstance(places, int):
            return False
        step = Decimal(1).scaleb(places)
        for figure in self.allowed:
            if len(figure) > 15 or int(figure) < size:
                continue
            whole = Decimal(figure) / size
            if value in (
                whole.quantize(step, rounding=ROUND_HALF_UP),
                whole.quantize(step, rounding=ROUND_DOWN),
            ):
                return True
        return False

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
