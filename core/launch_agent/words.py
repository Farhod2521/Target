"""What the advert chat says: every question, button and line is written
here, in Uzbek, and chosen by the brief - never composed by a model. That
is what keeps an answer short, the same every time, and free of anything
nobody checked.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Literal

from core.launch_agent.brief import (
    FORM_AUTO,
    FORM_NEW,
    FORM_OWN,
    KIND_NO,
    KIND_YES,
    Brief,
    Frame,
    GoalFrame,
    Slot,
    checks_kind,
    is_ready,
    money,
    next_slot,
    wanted,
)
from core.launch_agent.hear import Note

Input = Literal["text", "url", "phone", "money", "none"]

OTHER_GOAL: Final = "other"
MAX_FORM_BUTTONS: Final = 3
BUDGET_STEPS: Final = (1, 2, 4)


@dataclass(frozen=True, slots=True)
class Option:
    """One button under a question: what it shows and what pressing it says."""

    label: str
    slot: str
    value: str
    # Marked for the page to draw first and stronger. Only ever set from
    # the targetolog's own advice.
    recommended: bool = False
    # Opens a dialog of the cabinet's instead of answering here.
    opens: str = ""


@dataclass(frozen=True, slots=True)
class Ask:
    """The one question a turn ends with."""

    slot: Slot
    text: str
    options: tuple[Option, ...] = ()
    input: Input = "text"
    hint: str = ""


@dataclass(frozen=True, slots=True)
class Chip:
    """One thing already settled, drawn above the conversation."""

    slot: str
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class Reply:
    """What one turn answers with."""

    lines: tuple[str, ...] = ()
    ask: Ask | None = None
    chips: tuple[Chip, ...] = field(default_factory=tuple)
    ready: bool = False


NOTES: Final[dict[str, str]] = {
    "unknown_goal": "Bunday maqsad bu akkauntda yo'q. Quyidagilardan birini tanlang.",
    "not_a_link": "Bu sayt manziliga o'xshamadi. Masalan: example.uz",
    "not_telegram": ("Telegram havolasini yoki @username yozing. Masalan: @kanalingiz"),
    "not_asked": "Bu maqsadga havola kerak emas, uni hisobga olmadim.",
    "not_a_phone": "Telefon raqami to'liq emas. Masalan: +998 90 123 45 67",
    "unknown_channel": "Bu sahifada bunday yozishma kanali yo'q.",
    "unknown_form": "Bunday forma topilmadi. Quyidagilardan birini tanlang.",
    "not_a_sum": "Summani raqam bilan yozing. Masalan: 5",
    "other_currency": "Byudjetni akkaunt valyutasida yozing.",
}
BELOW_FLOOR: Final = "Bu maqsad uchun kunlik byudjet kamida {floor} bo'lishi kerak."
NOT_UNDERSTOOD: Final = "Buni tushunmadim, qaytadan yozib bering."

ASKS: Final[dict[str, str]] = {
    "kind": "Biznesingiz nima bilan shug'ullanadi? Qisqa yozing.",
    "kind_check": "Biznesingiz: {kind}. To'g'rimi?",
    "offer": "Hozir nimani reklama qilamiz? Mahsulot, xizmat yoki aksiyani yozing.",
    "goal": "Reklamadan nima kerak?",
    "link": "Sayt manzilini yozing.",
    "link_telegram": "Telegram kanal, guruh yoki bot manzilini yozing.",
    "phone": "Qaysi raqamga qo'ng'iroq qilishsin?",
    "channel": "Mijozlar qayerga yozsin?",
    "form": "Qaysi forma bilan ariza yig'amiz?",
    "budget": "Kuniga qancha sarflaymiz?",
}
HINTS: Final[dict[str, str]] = {
    "link": "example.uz",
    "link_telegram": "@kanalingiz",
    "phone": "+998 90 123 45 67",
}
CHIP_LABELS: Final[dict[str, str]] = {
    "kind": "Biznes",
    "offer": "Reklama",
    "goal": "Maqsad",
    "link": "Havola",
    "phone": "Telefon",
    "channel": "Yozishma",
    "form": "Forma",
    "budget": "Kunlik byudjet",
}
FORM_LABELS: Final[dict[str, str]] = {
    FORM_AUTO: "AI tavsiya qilgan forma",
    FORM_NEW: "Yangi forma",
    FORM_OWN: "O'zim tanlayman",
}
KIND_YES_LABEL: Final = "Ha, to'g'ri"
KIND_NO_LABEL: Final = "Yo'q, boshqa"
READY: Final = "Sozlamalar tayyor. Endi post tanlang yoki rasm, video yuklang."
ADVISED: Final = "Sizning yo'nalishingizga «{goal}» tavsiya etiladi: {reason}"
SECOND: Final = "«{goal}» esa shunday holatda yaxshiroq: {when}"


def amount_words(minor: int, frame: Frame) -> str:
    """A sum as it is shown: ``$5`` or ``60 000 so'm``."""
    value = money(minor, frame)
    whole = value == value.to_integral_value()
    number = f"{value:,.0f}" if whole else f"{value:,.2f}"
    number = number.replace(",", " ")
    if frame.currency.upper() == "USD":
        return f"${number}"
    if frame.currency.upper() == "UZS":
        return f"{number} so'm"
    return f"{number} {frame.currency}"


def _goal_options(frame: Frame) -> tuple[Option, ...]:
    first = frame.advice.first if frame.advice is not None else ""
    second = frame.advice.second if frame.advice is not None else ""
    ranked = sorted(
        frame.goals,
        key=lambda goal: 0 if goal.key == first else 1 if goal.key == second else 2,
    )
    return tuple(
        Option(
            label=goal.label,
            slot="goal",
            value=goal.key,
            recommended=bool(first) and goal.key == first,
        )
        for goal in ranked
    )


def _budget_options(goal: GoalFrame | None, frame: Frame) -> tuple[Option, ...]:
    if goal is not None and goal.budgets:
        unit = Decimal(frame.minor_per_unit)
        return tuple(
            Option(
                label=amount_words(int(Decimal(sum_) * unit), frame),
                slot="budget",
                value=sum_,
            )
            for sum_ in goal.budgets
        )
    floor = goal.min_daily_minor if goal is not None else 0
    if floor <= 0:
        return ()
    # Whole units read better on a button than the floor to the cent.
    unit = frame.minor_per_unit
    start = -(-floor // unit) * unit
    return tuple(
        Option(
            label=amount_words(start * times, frame),
            slot="budget",
            value=str(Decimal(start * times) / Decimal(unit)),
        )
        for times in BUDGET_STEPS
    )


def _form_options(frame: Frame) -> tuple[Option, ...]:
    kept = tuple(
        Option(label=form.name, slot="form", value=form.id)
        for form in frame.forms[:MAX_FORM_BUTTONS]
    )
    return (
        Option(
            label=FORM_LABELS[FORM_AUTO], slot="form", value=FORM_AUTO, recommended=True
        ),
        *kept,
        Option(label=FORM_LABELS[FORM_NEW], slot="form", value=FORM_NEW),
        Option(label=FORM_LABELS[FORM_OWN], slot="form", value=FORM_OWN, opens="form"),
    )


def ask_for(slot: Slot, brief: Brief, frame: Frame) -> Ask:
    """The question for one slot, with the buttons that answer it."""
    goal = frame.goal(brief.goal)
    if slot == "goal":
        return Ask(
            slot=slot, text=ASKS[slot], options=_goal_options(frame), input="text"
        )
    if slot == "link":
        key = "link_telegram" if goal is not None and goal.telegram else "link"
        known = (
            (Option(label=frame.known_link, slot="link", value=frame.known_link),)
            if frame.known_link and key == "link"
            else ()
        )
        return Ask(
            slot=slot, text=ASKS[key], options=known, input="url", hint=HINTS[key]
        )
    if slot == "phone":
        known = (
            (Option(label=frame.known_phone, slot="phone", value=frame.known_phone),)
            if frame.known_phone
            else ()
        )
        return Ask(
            slot=slot, text=ASKS[slot], options=known, input="phone", hint=HINTS[slot]
        )
    if slot == "channel":
        channels = goal.channels if goal is not None else ()
        return Ask(
            slot=slot,
            text=ASKS[slot],
            options=tuple(
                Option(label=label, slot="channel", value=key)
                for key, label in channels
            ),
            input="none",
        )
    if slot == "form":
        return Ask(
            slot=slot, text=ASKS[slot], options=_form_options(frame), input="none"
        )
    if slot == "budget":
        floor = goal.min_daily_minor if goal is not None else 0
        hint = f"Kamida {amount_words(floor, frame)}" if floor > 0 else ""
        return Ask(
            slot=slot,
            text=ASKS[slot],
            options=_budget_options(goal, frame),
            input="money",
            hint=hint,
        )
    if slot == "kind" and checks_kind(brief, frame):
        return Ask(
            slot=slot,
            text=ASKS["kind_check"].format(kind=frame.kind_label),
            options=(
                Option(label=KIND_YES_LABEL, slot="kind", value=KIND_YES),
                Option(label=KIND_NO_LABEL, slot="kind", value=KIND_NO),
            ),
            input="text",
        )
    if slot == "offer" and frame.offers:
        return Ask(
            slot=slot,
            text=ASKS[slot],
            options=tuple(
                Option(label=label, slot="offer", value=words)
                for label, words in frame.offers
            ),
            input="text",
        )
    return Ask(slot=slot, text=ASKS[slot], input="text")


def note_words(note: Note, frame: Frame) -> str:
    if note.code == "below_floor":
        try:
            floor = int(note.detail)
        except ValueError:
            floor = 0
        return BELOW_FLOOR.format(floor=amount_words(floor, frame))
    return NOTES.get(note.code, NOT_UNDERSTOOD)


def advice_lines(frame: Frame) -> tuple[str, ...]:
    """Why a goal is recommended - only ever the targetolog's own words."""
    advice = frame.advice
    if advice is None:
        return ()
    first = frame.goal(advice.first)
    if first is None or not advice.reason_first:
        return ()
    lines = [ADVISED.format(goal=first.label, reason=advice.reason_first)]
    second = frame.goal(advice.second)
    if second is not None and advice.when_second:
        lines.append(SECOND.format(goal=second.label, when=advice.when_second))
    return tuple(lines)


def _value_words(slot: str, brief: Brief, frame: Frame) -> str:
    if slot == "kind":
        # The kind as it was filed, once it is; their own words until then
        # - and instead of a reading they said no to. One still waiting for
        # their yes is in the question, not among what is settled.
        if checks_kind(brief, frame):
            return ""
        if frame.kind_guessed and brief.kind_ok == KIND_NO and not brief.kind_set:
            return brief.kind_said
        return frame.kind_label or brief.kind_said
    if slot == "goal":
        goal = frame.goal(brief.goal)
        return goal.label if goal is not None else ""
    if slot == "channel":
        goal = frame.goal(brief.goal)
        labels = dict(goal.channels) if goal is not None else {}
        return labels.get(brief.channel, brief.channel)
    if slot == "form":
        names = {form.id: form.name for form in frame.forms}
        return FORM_LABELS.get(brief.form) or names.get(brief.form, "")
    if slot == "budget":
        return amount_words(brief.budget_minor, frame) if brief.budget_minor else ""
    return str(getattr(brief, slot, ""))


def chips(brief: Brief, frame: Frame) -> tuple[Chip, ...]:
    """What is settled so far, in the order it was asked."""
    slots: list[str] = list(wanted(brief, frame))
    if frame.kind_known and frame.kind_label and "kind" not in slots:
        slots.insert(0, "kind")
    found = []
    for slot in slots:
        value = _value_words(slot, brief, frame)
        if value:
            found.append(Chip(slot=slot, label=CHIP_LABELS[slot], value=value))
    return tuple(found)


def reply(
    brief: Brief,
    frame: Frame,
    *,
    notes: tuple[Note, ...] = (),
    understood: bool = True,
) -> Reply:
    """What to say now: why something was not taken, then the next question
    - or that everything is settled."""
    lines = [note_words(note, frame) for note in notes]
    if not understood and not lines:
        lines.append(NOT_UNDERSTOOD)
    slot = next_slot(brief, frame)
    if slot is None:
        return Reply(
            lines=(*lines, READY),
            chips=chips(brief, frame),
            ready=is_ready(brief, frame),
        )
    if slot == "goal":
        lines += advice_lines(frame)
    return Reply(
        lines=tuple(lines),
        ask=ask_for(slot, brief, frame),
        chips=chips(brief, frame),
    )


__all__ = [
    "Ask",
    "Chip",
    "Option",
    "Reply",
    "advice_lines",
    "amount_words",
    "ask_for",
    "chips",
    "note_words",
    "reply",
]
