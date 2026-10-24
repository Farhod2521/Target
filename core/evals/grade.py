"""Marking one answer, with the checks the product already runs on it."""

import re
from dataclasses import dataclass
from typing import Final

from core.agent.copy_words import normalize
from core.chat.numbers import figures_in
from core.chat.verify import FigureGate
from core.evals.cases import Case

CYRILLIC = frozenset(range(0x0400, 0x0500))

NAMED: Final = re.compile(r"«[^»]*»")

SCREENS: Final = frozenset(
    {"reklama", "amallar", "mijozlar", "raqamlar", "hisobotlar", "kabinet"}
)

ENGLISH: Final = re.compile(
    r"\b(campaigns?|adsets?|ad sets?|leads?|conversions?|impressions?"
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
    """Whether every figure in the answer was in what the model was shown."""
    gate = FigureGate(
        allowed=figures_in(case.context),
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
    """Words this question's answer may not contain."""
    text = normalize(answer)
    said = [word for word in case.forbidden if normalize(word) in text]
    return Mark("no_forbidden_words", not said, ", ".join(said))


def _required(*, case: Case, answer: str) -> Mark:
    """At least one of the words this question has to be answered with."""
    if not case.required:
        return Mark("says_what_it_must", True)
    text = normalize(answer)
    found = any(normalize(word) in text for word in case.required)
    return Mark("says_what_it_must", found, "" if found else f"none of {case.required}")


def _script(*, case: Case, answer: str) -> Mark:
    """Latin where the reader's screens are Latin."""
    if case.language != "uz":
        return Mark("right_script", True)
    stray = [char for char in answer if ord(char) in CYRILLIC]
    return Mark("right_script", not stray, "".join(sorted(set(stray)))[:20])


def _house(*, case: Case, answer: str) -> Mark:
    """The marks an answer is set with, where the surface has them."""
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
