from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.metrics import Outcome
from core.metrics.outcomes import SITE_GOAL, outcome_for

UNCOUNTED_NOTES: dict[str, Any] = {
    "OFFSITE_CONVERSIONS": "Bu reklamaning natijasi sizning saytingizda sanaladi — bu yerda murojaat soni ko'rinmaydi."
}


@dataclass(frozen=True, slots=True)
class ResultText:
    field: str
    one: Any
    label: Any
    cost_label: Any
    hint: Any
    headline_note: Any
    source_note: Any = ""
    per: int = 1


RESULT_WORDS: dict[Outcome, "ResultText"] = {
    "chat": ResultText(
        field="results",
        one="suhbat",
        label="Suhbatlar",
        cost_label="Suhbat narxi",
        hint="Reklamadan keyin sizga yozganlar.",
        headline_note="Bitta suhbat sizga shuncha turdi - reklamaga sarflangan pul shu davrda boshlangan suhbatlarga bo'lingani.",
    ),
    "call": ResultText(
        field="results",
        one="qo'ng'iroq",
        label="Qo'ng'iroqlar",
        cost_label="Qo'ng'iroq narxi",
        hint="Reklamadagi raqamga qo'ng'iroq qilganlar.",
        headline_note="Bitta qo'ng'iroq sizga shuncha turdi - reklamaga sarflangan pul shu davrdagi qo'ng'iroqlarga bo'lingani.",
    ),
    "view": ResultText(
        field="impressions",
        one="ko'rish",
        label="Ko'rishlar",
        cost_label="Ming ko'rish narxi",
        hint="Reklamangiz necha marta ekranga chiqdi.",
        headline_note="Reklamangizni ming marta ko'rsatish shuncha turdi - sarflangan pul ko'rsatishlar soniga bo'lingani.",
        per=1000,
    ),
    "click": ResultText(
        field="results",
        one="o'tish",
        label="Saytga o'tishlar",
        cost_label="Bitta o'tish narxi",
        hint="Reklamadan sizning saytingizga o'tganlar.",
        headline_note="Saytingizga bitta o'tish shuncha turdi - reklamaga sarflangan pul o'tganlar soniga bo'lingani.",
    ),
    "site_lead": ResultText(
        field="leads_reported",
        one="murojaat",
        label="Saytdagi murojaatlar",
        cost_label="Murojaat narxi",
        hint="Saytingizdagi formani to'ldirganlar - Meta hisobi bo'yicha.",
        headline_note="Bitta murojaat sizga shuncha turdi - reklamaga sarflangan pul Meta saytingizda sanagan murojaatlarga bo'lingani.",
        source_note="Meta hisobi bo'yicha",
    ),
    "recall": ResultText(
        field="recallers",
        one="eslab qolgan",
        label="Eslab qolganlar",
        cost_label="Bitta eslab qolgan narxi",
        hint="Reklamangizni eslab qoladiganlar - platforma bahosi.",
        headline_note="Reklamangizni eslab qoladigan bitta odam shuncha turdi - sarflangan pul platformaning bahosiga bo'lingani.",
    ),
    "profile": ResultText(
        field="profile_visits",
        one="profilga o'tish",
        label="Profilga o'tishlar",
        cost_label="Profilga o'tish narxi",
        hint="Reklamani bosib Instagram profilingizga o'tganlar.",
        headline_note="Profilingizga bitta o'tish shuncha turdi - reklamaga sarflangan pul profilga o'tganlar soniga bo'lingani.",
    ),
}


def counted_result(
    optimization_goal: str, promoted_object: Mapping[str, object] | None = None
) -> tuple[str, Any] | None:
    text = RESULT_WORDS.get(outcome_for(optimization_goal, promoted_object))
    return (text.field, text.one) if text is not None else None


def uncounted_note(
    optimization_goal: str, promoted_object: Mapping[str, object] | None = None
) -> Any:
    if outcome_for(optimization_goal, promoted_object) != "none":
        return ""
    return UNCOUNTED_NOTES.get(optimization_goal.strip().upper(), "")


LEAD_TEXT: "ResultText" = ResultText(
    field="leads",
    one="murojaat",
    label="Murojaatlar",
    cost_label="Murojaat narxi",
    hint="Reklamadagi formani to'ldirganlar.",
    headline_note="Bitta murojaat sizga shuncha turdi - reklamaga sarflangan pul shu davrda kelgan murojaatlarga bo'lingani.",
)
OTHER_TEXT: "ResultText" = ResultText(
    field="",
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
