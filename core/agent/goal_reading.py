"""What the first screen does with a reading of the owner's own words."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from core.agent.schemas import GoalChoice, GoalIntent

ReadingState = Literal["found", "two", "unclear", "sale"]

SALE_FALLBACK: Final = "traffic"

MAX_GOALS: Final = 2

APOSTROPHES: Final = str.maketrans(
    dict.fromkeys("\u02bb\u02bc\u2018\u2019`\u00b4", "'")
)


@dataclass(frozen=True, slots=True)
class GoalReading:
    """One settled reading: what to show, and the words it rests on."""

    state: ReadingState
    goals: tuple[str, ...]
    quote: str = ""


def read_goal(intent: GoalIntent, *, offered: Sequence[str], text: str) -> GoalReading:
    """Settle the model's answer against the goals this business may run."""
    goals = tuple(dict.fromkeys(goal for goal in intent.goals if goal in offered))
    if len(goals) == 1:
        return GoalReading(
            state="found", goals=goals, quote=_quoted(intent.quote, text)
        )
    if len(goals) >= MAX_GOALS:
        return GoalReading(state="two", goals=goals[:MAX_GOALS])
    if intent.wants_sale and SALE_FALLBACK in offered:
        return GoalReading(state="sale", goals=(SALE_FALLBACK,))
    return GoalReading(state="unclear", goals=())


SALE_FALLBACK_ROW: Final = "site_page_views"

MAX_ALTERNATIVES: Final = 2

ChoiceState = Literal["found", "unclear", "sale"]


@dataclass(frozen=True, slots=True)
class ChoiceReading:
    """One settled reading of the table: the row, and what else fits."""

    state: ChoiceState
    row: str = ""
    alternatives: tuple[str, ...] = ()
    quote: str = ""


def read_goal_choice(
    intent: GoalChoice, *, rows: Sequence[str], text: str
) -> ChoiceReading:
    """Settle the model's answer against the rows this business may see."""
    given = (intent.choice, *intent.alternatives) if intent.choice.strip() else ()
    named = [key for key in given if key in rows]
    ordered = tuple(dict.fromkeys(named))
    if ordered:
        return ChoiceReading(
            state="found",
            row=ordered[0],
            alternatives=ordered[1 : 1 + MAX_ALTERNATIVES],
            quote=_quoted(intent.quote, text),
        )
    if intent.wants_sale and SALE_FALLBACK_ROW in rows:
        return ChoiceReading(state="sale", row=SALE_FALLBACK_ROW)
    return ChoiceReading(state="unclear")


def _quoted(quote: str, text: str) -> str:
    """The quote, only if the owner actually wrote it."""
    words = quote.strip()
    if words and _plain(words) in _plain(text):
        return words
    return ""


def _plain(value: str) -> str:
    return " ".join(value.translate(APOSTROPHES).casefold().split())
