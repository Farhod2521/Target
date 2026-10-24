"""What the first screen does with a reading of the owner's own words.

The model proposes and this decides what may reach the screen. A key the
business cannot launch is dropped, a quote the owner did not write is
dropped, and a sale - which no goal on offer can build - becomes the
nearest goal that can.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from core.agent.schemas import GoalChoice, GoalIntent

ReadingState = Literal["found", "two", "unclear", "sale"]

# The goal offered to somebody who asked for online sales. A visit to the
# site is the part of a sale an advert can bring without a pixel on it.
SALE_FALLBACK: Final = "traffic"

# How many results one reading may put in front of somebody. One campaign
# works toward one result, so a third option would only be a longer list.
MAX_GOALS: Final = 2

# Uzbek writes the o' and g' apostrophe four ways, and a model copying a
# phrase back tends to normalise it.
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
    """Settle the model's answer against the goals this business may run.

    "Unclear" is an answer rather than a failure. A guess shown with a tick
    beside it is how a campaign gets launched toward the wrong result, and
    asking somebody to say one more sentence costs them five seconds.
    """
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


# The row offered to somebody who asked for online sales: a visit to the
# site, counted when the page opens - the part of a sale an advert can bring
# without a purchase being built.
SALE_FALLBACK_ROW: Final = "site_page_views"

# How many other rows one reading may put beside its choice.
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
    """Settle the model's answer against the rows this business may see.

    A key not in the table is dropped. A dropped choice is replaced by the
    first alternative that survives, because the model named that one too;
    with none left the reading is unclear, never a guess.

    A row that is closed for this account is still a valid answer - the
    screen shows it with its reason and an open row beside it.
    """
    # No choice at all is the model declining to guess, and the
    # alternatives beside nothing are not promoted into one.
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
    """The quote, only if the owner actually wrote it.

    It is shown in quotation marks as their words, so a paraphrase would be
    a sentence put in their mouth. Compared without case, spacing or
    apostrophe differences, which are the ways a faithful copy still drifts.
    """
    words = quote.strip()
    if words and _plain(words) in _plain(text):
        return words
    return ""


def _plain(value: str) -> str:
    return " ".join(value.translate(APOSTROPHES).casefold().split())
