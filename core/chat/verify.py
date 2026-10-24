"""The gate a figure has to pass before it reaches the screen.

Chat that writes "your cost per lead is 15 000" and is wrong about it ends
the account's trust in everything else the product says. A prompt rule is
not enough for that - the same reasoning that put the refusal inside
``AudienceMemberDTO`` rather than inside a prompt.

So the check is in the transport. Claude's answer arrives in pieces, and a
run of digits is held back until it is complete and known: a figure the
context supplied, a figure the person themselves typed, or a small number
that is language rather than measurement. Anything else never reaches the
browser at all.

**What makes a number a claim is what it is attached to, not its size.**
"3 USD", "0,25 USD" and "7 ta murojaat" are the figures a small business
reads most often - dollar prices and lead counts are small - and a size
threshold waved every one of them through. So a number followed by money,
a per-cent sign or a result is checked however small; a number followed by
an age, a distance or a stretch of time is a quantity of the sentence's own
and passes under a hundred; and a number attached to nothing passes only
from one to ten.

**A word can make a small number large.** "8 million so'm" and "5 foiz" are
eight and five in the text; what they say about the account is six orders
of magnitude and a share. Both would have passed a size threshold, so the
word after the digits is what decides - see :data:`CLAIMED_BY`.

Checking afterwards would not work. By the time an answer has finished
streaming, the number is already on the screen and has already been read.
"""

import re
from dataclasses import dataclass, field
from typing import Final

from core.chat.numbers import FIGURE, GAPS, canonical

# What replaces a figure that did not come from anywhere.
#
# Not a dash. "Sizning CPL - so'm" reads as a sentence with a value in it
# and invites the reader to supply one; this reads as a hole, which is what
# it is. Short on purpose - it appears mid-sentence, and the sentence
# around it is usually the model's reasoning, which is worth keeping.
MARKER: Final = "[?]"

# Below this, a number followed by an age, a distance or a stretch of time
# is a quantity of the sentence rather than a measurement of the account:
# "25 yoshdan", "5 km", "3 kun kuting".
GENERIC_BELOW: Final = 100

# Below this, a number attached to nothing is language: "2-3 ta rasm",
# "birinchi 5 kun". Two to ten is how often a sentence counts things.
BARE_BELOW: Final = 11

# The figure, and whether a per-cent sign follows it.
CLAIM: Final = re.compile(rf"({FIGURE.pattern})(%)?")

# The apostrophes an Uzbek word is written with: the typewriter one, the
# turned comma of the Latin alphabet, and the right quote a phone puts in.
_APOSTROPHE: Final = "['\u02bb\u2019`]"
# One letter of a word, apostrophes included - "so'm", "qo'ng'iroq".
_LETTER: Final = rf"(?:[^\W\d_]|{_APOSTROPHE})"

# Russian stems, as a reply in Russian writes them.
_RUSSIAN: Final = (
    "сум|сўм|руб|долл|евро|"  # noqa: RUF001 - Russian, not look-alikes
    "заяв|лид|диалог|звон|клик|переход|показ|процент"
)

# The words that make a small number into a large one. "8 million so'm" is
# eight in the text and eight million in the account: read as a bare eight
# it passes for language, and the sentence that carries it is a claim about
# somebody's money off by six orders of magnitude. The scale word decides,
# so it is asked for here rather than left to the size of the digits.
_SCALE: Final = (
    "ming|million|milliard|mln|mlrd|thousand|billion|тыс|миллион|миллиард|млн|млрд"
)

# What makes the number before it a claim about the account, whatever its
# size: money, a share, a result, a scale or a comparison - in the three
# languages an answer is written in. "ta" alone is Uzbek for "pieces" and
# counts anything; it is a claim only in front of a result.
CLAIMED_BY: Final = re.compile(
    rf"\s?(?:ta\s+)?(?:%|usd|uzs|eur|rub|kzt|dollar|euro|evro|so{_APOSTROPHE}m|"
    rf"(?:som|sum)(?:\b|ga\b|dan\b|lik)|"
    rf"murojaat|lid\b|lead|suhbat|conversation|qo{_APOSTROPHE}?ng{_APOSTROPHE}?iroq|"
    rf"call|bosish|click|o{_APOSTROPHE}?tish|visit|ko{_APOSTROPHE}?rish|marta|"
    rf"times|foiz|percent|barobar|baravar|{_SCALE}|{_RUSSIAN})",
    re.IGNORECASE,
)
# The same, written in front of it.
MONEY_BEFORE: Final = re.compile(r"[$€₽]\s?$")

# A head count: "500 000 kishilik hudud", "1 million odam". For a visitor
# there is no account for it to misreport - the prompt itself calls "at
# least 1000 people in an audience" fine - so the gate lets it through when
# told to; see ``FigureGate.people_below``. A scale word in between is part
# of the count, not a claim about money.
PEOPLE: Final = re.compile(
    rf"\s?(?:(?:{_SCALE})\s+)?(?:kishi|odam|people|persons?|человек)",
    re.IGNORECASE,
)

# What makes a number under a hundred a quantity of the sentence's own.
# Seconds are here for the video an answer may plan: "0-3 soniya", "15
# soniyalik video" are the length of a shot, not a figure of the account.
_RUSSIAN_TIME: Final = "лет|год|км|дн|день|час|мин|сек|недел|месяц"
QUANTITY: Final = re.compile(
    rf"\s?(?:[-\u2013\u2014]\s?\d+\s?)?(?:yosh|years?|km|kun|days?|soat|hours?|daqiqa|"
    rf"minutes?|soniya|sekund|seconds?|hafta|weeks?|oy\b|months?|{_RUSSIAN_TIME})",
    re.IGNORECASE,
)

# The screen shapes a video plan names: "tik video (9:16)". Two numbers
# joined by a colon are one shape, not two figures of the account.
RATIOS: Final = frozenset({"9:16", "16:9", "1:1", "4:5", "4:3", "3:4"})
RATIO: Final = re.compile(r"(?<!\d)\d{1,2}:\d{1,2}(?!\d)")

# What is held back at the end of a piece: a figure that may not be
# finished, and the word after it that decides whether it is a claim - "3"
# arriving now can be "3 USD" or "3 ta murojaat" in the next piece. The
# first half of a ratio or a range is held with it, so "9:" and "16" are
# judged as one, and so is "15-" with the "20 soniya" that decides it.
_OPENING: Final = r"\d{1,2}:|\d+\s?[-\u2013\u2014]\s?"
HELD: Final = re.compile(
    rf"(?:{_OPENING})?\d[\d{GAPS},.]*(?:[{GAPS}]?(?:ta[{GAPS}]+)?{_LETTER}{{0,14}}%?)?$"
    rf"|(?:{_OPENING})$"
)


@dataclass(slots=True)
class FigureGate:
    """Passes text through, holding every figure up to the light.

    Stateful across chunks because a figure is: "15" arriving at the end of
    one piece becomes "15 000" at the start of the next, and a gate that
    judged the piece would mask a number that was never wrong.
    """

    allowed: frozenset[str]
    # Figures the person typed themselves. Quoting somebody's own number
    # back at them is not a claim about their account.
    quoted: frozenset[str] = frozenset()
    marker: str = MARKER
    generic_below: int = GENERIC_BELOW
    # Head counts under this pass. Zero - none - where there is an account
    # whose audience an invented count would misreport; a visitor's answer
    # raises it, because a visitor has no account to misreport.
    people_below: int = 0
    masked: int = 0
    _tail: str = field(default="", repr=False)

    def feed(self, text: str) -> str:
        """The part of ``text`` that is safe to show now.

        What is held back is only ever a trailing run of digits, so the
        delay is a few characters and never a sentence.
        """
        buffer = self._tail + text
        unfinished = HELD.search(buffer)
        if unfinished is None:
            self._tail = ""
            return self._judge(buffer)

        self._tail = buffer[unfinished.start() :]
        return self._judge(buffer[: unfinished.start()])

    def allow(self, figures: frozenset[str]) -> None:
        """Let these figures through from now on.

        For figures the assistant was handed after the answer started: a
        look-up's result arrives between two rounds of the same answer, and
        the text written after it may quote what it returned. Added, never
        replaced - what the context supplied stays allowed.
        """
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
        # The per-cent sign goes with it. "[?]%" still reads as a
        # measurement; the marker alone reads as a missing one.
        return self.marker

    def _is_language(self, match: re.Match[str], value: int) -> bool:
        """Whether a figure nobody supplied is a word of the sentence.

        A head count, where the gate was told to pass them. Never when
        money or a result is attached to it, before or after. Under a
        hundred when it counts years, kilometres or days; from one to ten
        when it counts nothing in particular.
        """
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
