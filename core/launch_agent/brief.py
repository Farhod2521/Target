"""What the advert chat has to learn before an advert can be prepared.

The chat is a form filled in conversation. ``Brief`` is the form: each slot
is one thing the launch needs. ``Frame`` is what the account allows right
now - the goals on offer and what each one asks for - gathered by the
caller. Nothing here speaks to a model or a database: given the same brief
and frame it always asks the same next question, which is what makes the
chat exact rather than talkative.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Final, Literal

Slot = Literal["kind", "offer", "goal", "link", "phone", "channel", "form", "budget"]

# The order the questions are asked in. A later slot is never asked while
# an earlier one is empty.
ORDER: Final[tuple[Slot, ...]] = (
    "kind",
    "offer",
    "goal",
    "link",
    "phone",
    "channel",
    "form",
    "budget",
)

FORM_AUTO: Final = "auto"
FORM_NEW: Final = "new"
FORM_OWN: Final = "own"
START_DAYS: Final = ("today", "tomorrow")


@dataclass(frozen=True, slots=True)
class GoalFrame:
    """One goal on offer, and what choosing it asks for."""

    key: str
    label: str
    min_daily_minor: int = 0
    needs_link: bool = False
    # The link must be a Telegram one (a channel, a group, a bot).
    telegram: bool = False
    needs_phone: bool = False
    opens_chat: bool = False
    channels: tuple[tuple[str, str], ...] = ()
    needs_form: bool = False
    # Daily sums to offer as buttons, in whole units, as the first screen
    # offers them; empty: worked out from the floor.
    budgets: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FormOption:
    """A lead form the page already has."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class GoalAdvice:
    """What the targetolog advises this kind of business. ``None`` on the
    frame until the office has written it: the goals are then listed with
    no recommendation and no reason."""

    first: str
    reason_first: str = ""
    second: str = ""
    when_second: str = ""


@dataclass(frozen=True, slots=True)
class Frame:
    """What this account allows, as of this turn."""

    goals: tuple[GoalFrame, ...]
    currency: str = "USD"
    # Minor units in one whole unit: 100 for dollars, 1 for so'm.
    minor_per_unit: int = 100
    # So'm for one dollar, for a budget said in so'm. 0: not known.
    uzs_per_usd: int = 0
    kind_known: bool = True
    kind_label: str = ""
    forms: tuple[FormOption, ...] = ()
    advice: GoalAdvice | None = None
    # The link and the phone the business already has, offered as a button.
    known_link: str = ""
    known_phone: str = ""
    # What the business is known to sell, offered as buttons when asking
    # what to advertise: ``(label, words)``.
    offers: tuple[tuple[str, str], ...] = ()

    def goal(self, key: str) -> GoalFrame | None:
        return next((one for one in self.goals if one.key == key), None)


@dataclass(frozen=True, slots=True)
class Brief:
    """What has been learned so far. Empty means not said yet."""

    kind_said: str = ""
    offer: str = ""
    goal: str = ""
    link: str = ""
    phone: str = ""
    channel: str = ""
    form: str = ""
    budget_minor: int = 0
    start_day: str = "today"
    # The one thing this advert sells, when the person named it: what the
    # business's knowledge is offered once the questions are answered.
    sold_name: str = ""
    sold_price: str = ""
    # The proposal that offer became on the business's waiting list.
    memo: str = ""
    # Slots the person filled themselves, as against ones we defaulted.
    said: frozenset[str] = field(default_factory=frozenset)

    def with_(self, **changes: object) -> "Brief":
        return replace(self, **changes)  # type: ignore[arg-type]


def wanted(brief: Brief, frame: Frame) -> tuple[Slot, ...]:
    """The slots this brief needs, in order - the goal decides the later ones."""
    slots: list[Slot] = []
    if not frame.kind_known:
        slots.append("kind")
    slots += ["offer", "goal"]
    goal = frame.goal(brief.goal)
    if goal is not None:
        if goal.needs_link:
            slots.append("link")
        if goal.needs_phone:
            slots.append("phone")
        if goal.opens_chat and len(goal.channels) > 1:
            slots.append("channel")
        if goal.needs_form:
            slots.append("form")
    slots.append("budget")
    return tuple(slots)


def _filled(brief: Brief, slot: Slot) -> bool:
    if slot == "kind":
        return bool(brief.kind_said)
    if slot == "budget":
        return brief.budget_minor > 0
    return bool(getattr(brief, slot))


def missing(brief: Brief, frame: Frame) -> tuple[Slot, ...]:
    """What is still to be asked, in the order it is asked."""
    return tuple(slot for slot in wanted(brief, frame) if not _filled(brief, slot))


def next_slot(brief: Brief, frame: Frame) -> Slot | None:
    left = missing(brief, frame)
    return left[0] if left else None


def is_ready(brief: Brief, frame: Frame) -> bool:
    """Whether everything the plan step saves has been said."""
    return not missing(brief, frame)


def money(minor: int, frame: Frame) -> Decimal:
    """Minor units as the whole-unit amount the plan step is given."""
    return Decimal(minor) / Decimal(frame.minor_per_unit)


__all__ = [
    "FORM_AUTO",
    "FORM_NEW",
    "FORM_OWN",
    "ORDER",
    "START_DAYS",
    "Brief",
    "FormOption",
    "Frame",
    "GoalAdvice",
    "GoalFrame",
    "Slot",
    "is_ready",
    "missing",
    "money",
    "next_slot",
    "wanted",
]
