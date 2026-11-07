from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from core.metrics import Outcome
from core.metrics.formulas import RESULT_OF, result_per
from core.metrics.outcomes import (
    SITE_GOAL,
    is_custom_conversion,
    outcome_for,
    site_event,
)

UNCOUNTED_NOTES: dict[str, Any] = {
    "OFFSITE_CONVERSIONS": "Bu reklamaning natijasi sizning saytingizda sanaladi — bu yerda murojaat soni ko'rinmaydi."
}


@dataclass(frozen=True, slots=True)
class ResultText:
    """The words for one goal's result. What it counts and per how many of
    them its cost is quoted come from :data:`core.metrics.formulas.RESULT_OF`."""

    outcome: Outcome
    one: Any
    label: Any
    cost_label: Any
    hint: Any
    headline_note: Any
    source_note: Any = ""

    @property
    def field(self) -> str:
        found = RESULT_OF.get(self.outcome)
        return found[0] if found else ""

    @property
    def per(self) -> int:
        return result_per(self.outcome)


RESULT_WORDS: dict[Outcome, "ResultText"] = {
    "chat": ResultText(
        outcome="chat",
        one="suhbat",
        label="Suhbatlar",
        cost_label="Suhbat narxi",
        hint="Reklamadan keyin sizga yozganlar.",
        headline_note="Bitta suhbat sizga shuncha turdi - reklamaga sarflangan pul shu davrda boshlangan suhbatlarga bo'lingani.",
    ),
    "call": ResultText(
        outcome="call",
        one="qo'ng'iroq",
        label="Qo'ng'iroqlar",
        cost_label="Qo'ng'iroq narxi",
        hint="Reklamadagi raqamga qo'ng'iroq qilganlar.",
        headline_note="Bitta qo'ng'iroq sizga shuncha turdi - reklamaga sarflangan pul shu davrdagi qo'ng'iroqlarga bo'lingani.",
    ),
    "view": ResultText(
        outcome="view",
        one="ko'rish",
        label="Ko'rishlar",
        cost_label="Ming ko'rish narxi",
        hint="Reklamangiz necha marta ekranga chiqdi.",
        headline_note="Reklamangizni ming marta ko'rsatish shuncha turdi - sarflangan pul ko'rsatishlar soniga bo'lingani.",
    ),
    "click": ResultText(
        outcome="click",
        one="o'tish",
        label="Saytga o'tishlar",
        cost_label="Bitta o'tish narxi",
        hint="Reklamadan sizning saytingizga o'tganlar.",
        headline_note="Saytingizga bitta o'tish shuncha turdi - reklamaga sarflangan pul o'tganlar soniga bo'lingani.",
    ),
    "site_lead": ResultText(
        outcome="site_lead",
        one="murojaat",
        label="Saytdagi murojaatlar",
        cost_label="Murojaat narxi",
        hint="Saytingizdagi formani to'ldirganlar - Meta hisobi bo'yicha.",
        headline_note="Bitta murojaat sizga shuncha turdi - reklamaga sarflangan pul Meta saytingizda sanagan murojaatlarga bo'lingani.",
        source_note="Meta hisobi bo'yicha",
    ),
    "recall": ResultText(
        outcome="recall",
        one="eslab qolgan",
        label="Eslab qolganlar",
        cost_label="Bitta eslab qolgan narxi",
        hint="Reklamangizni eslab qoladiganlar - platforma bahosi.",
        headline_note="Reklamangizni eslab qoladigan bitta odam shuncha turdi - sarflangan pul platformaning bahosiga bo'lingani.",
    ),
    "profile": ResultText(
        outcome="profile",
        one="profilga o'tish",
        label="Profilga o'tishlar",
        cost_label="Profilga o'tish narxi",
        hint="Reklamani bosib Instagram profilingizga o'tganlar.",
        headline_note="Profilingizga bitta o'tish shuncha turdi - reklamaga sarflangan pul profilga o'tganlar soniga bo'lingani.",
    ),
}


# TZ 3: a website event other than the pixel's Lead, counted from Meta's
# own results and named by the event - «29 ro'yxatdan o'tish».
EVENT_RESULT_WORDS: dict[str, Any] = {
    "LEAD": "murojaat",
    "CONTACT": "bog'lanish",
    "COMPLETE_REGISTRATION": "ro'yxatdan o'tish",
    "SUBMIT_APPLICATION": "ariza",
    "SCHEDULE": "uchrashuv belgilash",
    "START_TRIAL": "sinovni boshlash",
    "SUBSCRIBE": "obuna",
    "FIND_LOCATION": "manzilni topish",
    "CONTENT_VIEW": "sahifa ko'rish",
    "SEARCH": "qidiruv",
    "ADD_TO_CART": "savatga qo'shish",
    "ADD_TO_WISHLIST": "saqlanganlarga qo'shish",
    "INITIATED_CHECKOUT": "to'lovni boshlash",
    "ADD_PAYMENT_INFO": "to'lov ma'lumoti",
    "PURCHASE": "xarid",
    "DONATE": "xayriya",
}
SITE_EVENT_WORD: Final = "natija"


def site_event_result(
    optimization_goal: str, promoted_object: Mapping[str, object] | None
) -> tuple[str, Any] | None:
    """``("results", word)`` for a site event the outcomes leave uncounted."""
    if optimization_goal.strip().upper() != SITE_GOAL:
        return None
    if outcome_for(optimization_goal, promoted_object) != "none":
        return None
    event = site_event(promoted_object)
    if not event and not is_custom_conversion(promoted_object):
        return None
    return "results", EVENT_RESULT_WORDS.get(event, SITE_EVENT_WORD)


def counted_result(
    optimization_goal: str, promoted_object: Mapping[str, object] | None = None
) -> tuple[str, Any] | None:
    text = RESULT_WORDS.get(outcome_for(optimization_goal, promoted_object))
    if text is None:
        return site_event_result(optimization_goal, promoted_object)
    return text.field, text.one


def uncounted_note(
    optimization_goal: str, promoted_object: Mapping[str, object] | None = None
) -> Any:
    if outcome_for(optimization_goal, promoted_object) != "none":
        return ""
    if site_event_result(optimization_goal, promoted_object) is not None:
        return ""
    return UNCOUNTED_NOTES.get(optimization_goal.strip().upper(), "")


LEAD_TEXT: "ResultText" = ResultText(
    outcome="lead",
    one="murojaat",
    label="Murojaatlar",
    cost_label="Murojaat narxi",
    hint="Reklamadagi formani to'ldirganlar.",
    headline_note="Bitta murojaat sizga shuncha turdi - reklamaga sarflangan pul shu davrda kelgan murojaatlarga bo'lingani.",
)
OTHER_TEXT: "ResultText" = ResultText(
    outcome="none",
    one="natija",
    label="Boshqa reklama",
    cost_label="",
    hint="",
    headline_note="",
)
UNCOUNTED_LABEL = "sanalmaydi"
ON_SITE_LABEL = "Saytda sanaladi"
OTHER_NOTE = "Bu turdagi reklamaning natijasini bu yerda sanab bo'lmaydi - sarflangan pul ko'rsatilgan."


def screen_kind(
    optimization_goal: str, promoted_object: Mapping[str, object] | None = None
) -> Outcome:
    if not optimization_goal.strip():
        return "lead"
    return outcome_for(optimization_goal, promoted_object)


def words_for(kind: Outcome) -> "ResultText":
    if kind == "lead":
        return LEAD_TEXT
    return RESULT_WORDS.get(kind, OTHER_TEXT)


def sourced_label(kind: Outcome) -> str:
    words = words_for(kind)
    if words.source_note:
        return f"{words.label} ({words.source_note})"
    return str(words.label)


def uncounted_label(optimization_goal: str) -> Any:
    if optimization_goal.strip().upper() == SITE_GOAL:
        return ON_SITE_LABEL
    return UNCOUNTED_LABEL


def note_for(kind: Outcome, *, optimization_goals: "frozenset[str]") -> Any:
    if kind != "none":
        return ""
    if len(optimization_goals) == 1:
        specific = uncounted_note(next(iter(optimization_goals)))
        if specific:
            return specific
    return OTHER_NOTE


__all__ = [
    "LEAD_TEXT",
    "ON_SITE_LABEL",
    "OTHER_NOTE",
    "OTHER_TEXT",
    "RESULT_WORDS",
    "UNCOUNTED_LABEL",
    "UNCOUNTED_NOTES",
    "ResultText",
    "counted_result",
    "note_for",
    "screen_kind",
    "sourced_label",
    "uncounted_label",
    "uncounted_note",
    "words_for",
]
