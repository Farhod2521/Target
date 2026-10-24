"""Marking one answer, with the checks the product already runs on it.

**The graders are borrowed, not written.** Every answer a customer reads
goes through :class:`~core.chat.verify.FigureGate`, and every advert this
product proposes goes through :mod:`core.agent.copy_check`. Grading with a
second set of rules would measure the rules rather than the model, and the
first time the two disagreed the report would be wrong in the direction
nobody checks.

**Four questions, and none of them is "is this a good answer".** Whether a
paragraph is useful is not a thing a machine decides, and a score that
pretended otherwise would be the number everybody quoted. What is decidable
is narrower and worth more: did it invent a figure, did it use a word it
was told not to, did it answer in the reader's language, did it answer at
all. A run where all four hold is not proof the answer was good; a run
where one fails is proof it was not.
"""

import re
from dataclasses import dataclass
from typing import Final

from core.agent.copy_words import normalize
from core.chat.numbers import figures_in
from core.chat.verify import FigureGate
from core.evals.cases import Case

# Where a Cyrillic letter starts and ends. The only script question worth
# asking: an answer in Cyrillic to a reader whose screens are in Latin
# Uzbek is wrong whatever it says, and anything finer than the script is a
# second language model.
CYRILLIC = frozenset(range(0x0400, 0x0500))

# What the answer named, in the brackets this product names things with.
# Cut out before the marks below are looked for: what is inside is the
# account's own spelling, copied - a campaign somebody called "Guldasta -
# mart" is not the model writing a hyphen where a dash belongs.
NAMED: Final = re.compile(r"«[^»]*»")

# English words for things this product has its own word for. The prompt
# lists them as words never to write; this is the half of that list a
# check can be sure about - each one has a single ordinary Uzbek word, and
# none of them is part of a name the reader would recognise.
# The screens, as the answers name them. In «brackets» they read as a
# campaign somebody called Reklama, which is a thing an account can
# genuinely have - so the brackets are what tells the two apart, and a
# screen inside them takes that apart.
SCREENS: Final = frozenset(
    {"reklama", "amallar", "mijozlar", "raqamlar", "hisobotlar", "kabinet"}
)

ENGLISH: Final = re.compile(
    r"\b(campaigns?|adsets?|ad sets?|leads?|conversions?|impressions?"
    # "provider" is this product's neutral word for the platform, and the
    # reader has only ever seen "Meta". It arrives spelled into their own
    # alphabet as readily as in English, which is the form a rule about an
    # English word does not stop.
    r"|placements?|objectives?|lookalikes?|providers?|provayder|провайдер)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Mark:
    """One check, and what it found. ``detail`` is empty when it passed."""

    check: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Report:
    """One case's answer and every mark against it."""

    case_id: str
    surface: str
    answer: str
    marks: tuple[Mark, ...]
    # What the call cost, so a run's total is the sum of a column rather
    # than a figure somebody adds up by hand.
    cost_minor: int = 0
    currency: str = ""

    @property
    def passed(self) -> bool:
        return all(mark.passed for mark in self.marks)

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(mark.check for mark in self.marks if not mark.passed)


def grade(*, case: Case, answer: str) -> tuple[Mark, ...]:
    """Every check, in the order a reader would notice them failing."""
    return (
        _answered(answer),
        _figures(case=case, answer=answer),
        _forbidden(case=case, answer=answer),
        _required(case=case, answer=answer),
        _script(case=case, answer=answer),
        _house(case=case, answer=answer),
    )


def _answered(answer: str) -> Mark:
    """An empty answer passes every other check by saying nothing."""
    return Mark("answered", bool(answer.strip()), "" if answer.strip() else "empty")


def _figures(*, case: Case, answer: str) -> Mark:
    """Whether every figure in the answer was in what the model was shown.

    The allow-set is derived from the context by the same function the
    product uses, so this asks exactly what the live gate asks - and a
    failure here is a figure a customer would have seen replaced by a
    marker.
    """
    gate = FigureGate(
        allowed=figures_in(case.context),
        # The question's own figures, as both surfaces allow them: the
        # cabinet passes what the person typed, and the night passes the
        # shortlist it is answering. Without this a night note quoting the
        # entry it was handed would be marked as inventing it.
        quoted=figures_in(case.question),
    )
    gate.feed(answer)
    gate.flush()
    return Mark(
        "no_invented_figures",
        gate.masked == 0,
        "" if gate.masked == 0 else f"{gate.masked} masked",
    )


def _forbidden(*, case: Case, answer: str) -> Mark:
    """Words this question's answer may not contain.

    Normalised on both sides, because the words in question are Uzbek and
    arrive with whichever apostrophe the keyboard produced.
    """
    text = normalize(answer)
    said = [word for word in case.forbidden if normalize(word) in text]
    return Mark("no_forbidden_words", not said, ", ".join(said))


def _required(*, case: Case, answer: str) -> Mark:
    """At least one of the words this question has to be answered with.

    Any rather than all: the point of a case that names three is that the
    answer may reach the same place by any of them, and demanding the set
    would be grading the wording.
    """
    if not case.required:
        return Mark("says_what_it_must", True)
    text = normalize(answer)
    found = any(normalize(word) in text for word in case.required)
    return Mark("says_what_it_must", found, "" if found else f"none of {case.required}")


def _script(*, case: Case, answer: str) -> Mark:
    """Latin where the reader's screens are Latin.

    Only for a case that asks for Uzbek: Russian is Cyrillic and checking
    it this way would fail every correct answer.
    """
    if case.language != "uz":
        return Mark("right_script", True)
    stray = [char for char in answer if ord(char) in CYRILLIC]
    return Mark("right_script", not stray, "".join(sorted(set(stray)))[:20])


def _house(*, case: Case, answer: str) -> Mark:
    """The marks an answer is set with, where the surface has them.

    Only the ones a check can be sure about, and all of them are looked
    for outside «the brackets»: what a campaign is called is the account's
    spelling and the prompt says to copy it, so a name with a hyphen or a
    quotation mark in it is the rule being kept rather than broken.

    A hyphen between clauses is the mark the model reaches for by itself
    and reads as a minus in a sentence about money. A straight quotation
    mark is the other half of the same rule - this product names things in
    «these», and a name in "these" beside a screen in "these" leaves the
    reader working out which of the two is theirs. A table is the layout
    the rows replaced. An English word is the jargon rule broken by a
    model writing at speed: "reklama campaign" was in a real run.
    """
    if case.surface != "chat":
        return Mark("house_style", True)
    said = NAMED.sub("", answer)
    broken = []
    if " - " in said:
        broken.append("hyphen for dash")
    if '"' in said:
        broken.append("straight quotes")
    if "|--" in said or "--|" in said:
        broken.append("table")
    stray = sorted({found.group(0).lower() for found in ENGLISH.finditer(said)})
    if stray:
        broken.append(f"English: {', '.join(stray)}")
    screens = sorted(
        {
            found.group(0)
            for found in NAMED.finditer(answer)
            if found.group(0).strip("«»").lower() in SCREENS
        }
    )
    if screens:
        broken.append(f"screen in brackets: {', '.join(screens)}")
    return Mark("house_style", not broken, ", ".join(broken))


__all__ = ["CYRILLIC", "Mark", "Report", "grade"]
