"""A lead as a spreadsheet row, in the order the spreadsheet's columns stand.

The download's columns without the row number and the verdict, and with the
lead's own id first and hidden: it is how a run that lost Google's answer
finds out which of its rows made it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from zoneinfo import ZoneInfo

from googlekit import CellValue, SheetColumn

from app.common.i18n import get_language
from app.modules.destinations.constants import MAX_QUESTION_COLUMNS
from app.modules.leads.models import Lead
from app.modules.leads.selectors import extra_answers, lead_note

_PX_PER_CHAR = 7
_PX_MARGIN = 10
_ID_WIDTH_PX = 60
_QUESTION_WIDTH_CHARS = 24

# What Django's catalogues make of the words written into the owner's file,
# which is headed in the language they read the cabinet in.
WORDS: Final[dict[str, dict[str, str]]] = {
    "ru": {
        "Ism": "Имя",
        "Telefon": "Телефон",
        "Shahar": "Город",
        "Kelgan vaqt": "Время получения",
        "Reklama": "Реклама",
        "Kampaniya": "Кампания",
        "Forma": "Форма",
        "Izoh": "Пояснение",
        "Mijozlar": "Клиенты",
        "TargetologAI — Mijozlar": "TargetologAI — Клиенты",
        "TargetologAI — Boshqa formalar": "TargetologAI — Другие формы",
        "Sinov": "Пробный",
        "Reklamasiz": "Без рекламы",
    },
    "en": {
        "Ism": "Name",
        "Telefon": "Phone",
        "Shahar": "City",
        "Kelgan vaqt": "Received at",
        "Reklama": "Ads",
        "Kampaniya": "Campaign",
        "Forma": "Form",
        "Izoh": "Explanation",
        "Mijozlar": "Customers",
        "TargetologAI — Mijozlar": "TargetologAI — Customers",
        "TargetologAI — Boshqa formalar": "TargetologAI — Other forms",
        "Sinov": "Trial",
        "Reklamasiz": "Organic",
    },
}


def word(text: str) -> str:
    """``text`` in the active language; Uzbek is the source."""
    return WORDS.get(get_language(), {}).get(text, text)


def fixed_columns() -> tuple[SheetColumn, ...]:
    """The product's own columns, headed in the active language."""
    return (
        SheetColumn(header="ID", width_px=_ID_WIDTH_PX, hidden=True),
        SheetColumn(header=word("Ism"), width_px=_px(26)),
        SheetColumn(header=word("Telefon"), width_px=_px(18)),
        SheetColumn(header="Email", width_px=_px(26)),
        SheetColumn(header=word("Shahar"), width_px=_px(16)),
        SheetColumn(header=word("Kelgan vaqt"), width_px=_px(18)),
        SheetColumn(header=word("Reklama"), width_px=_px(30)),
        SheetColumn(header=word("Kampaniya"), width_px=_px(26)),
        SheetColumn(header=word("Forma"), width_px=_px(24)),
        SheetColumn(header=word("Izoh"), width_px=_px(14)),
    )


FIXED_COLUMN_COUNT = 10


def question_columns(questions: Sequence[str]) -> tuple[SheetColumn, ...]:
    """Columns for questions, headed with the advertiser's own words."""
    width = _px(_QUESTION_WIDTH_CHARS)
    return tuple(SheetColumn(header=question, width_px=width) for question in questions)


@dataclass(frozen=True, slots=True)
class SheetBatch:
    """Rows ready to append, and the headings they need that do not exist yet."""

    lead_ids: tuple[str, ...]
    rows: tuple[tuple[CellValue, ...], ...]
    new_questions: tuple[str, ...]


def sheet_batch(
    *,
    leads: Sequence[Lead],
    known: Sequence[str],
    zone: ZoneInfo | None,
    ad_names: Mapping[str, str],
    campaign_names: Mapping[str, str],
) -> SheetBatch:
    """The rows for ``leads``, and any question the spreadsheet lacks a column for.

    A new question goes after the last known one, never in between.
    """
    answers = [extra_answers(lead) for lead in leads]
    questions = _grown(known=known, answers=answers)
    rows = tuple(
        _row(
            lead=lead,
            answers=given,
            questions=questions,
            zone=zone,
            ad_names=ad_names,
            campaign_names=campaign_names,
        )
        for lead, given in zip(leads, answers, strict=True)
    )
    return SheetBatch(
        lead_ids=tuple(str(lead.id) for lead in leads),
        rows=rows,
        new_questions=tuple(questions[len(known) :]),
    )


def _grown(*, known: Sequence[str], answers: Sequence[Mapping[str, str]]) -> list[str]:
    questions = list(known)
    seen = set(questions)
    for given in answers:
        for label in given:
            if label not in seen and len(questions) < MAX_QUESTION_COLUMNS:
                questions.append(label)
                seen.add(label)
    return questions


def _row(
    *,
    lead: Lead,
    answers: Mapping[str, str],
    questions: Sequence[str],
    zone: ZoneInfo | None,
    ad_names: Mapping[str, str],
    campaign_names: Mapping[str, str],
) -> tuple[CellValue, ...]:
    note = lead_note(lead)
    return (
        str(lead.id),
        lead.full_name,
        lead.phone_e164,
        lead.email,
        lead.city,
        _local(lead.submitted_at, zone),
        ad_names.get(lead.ad_external_id, lead.ad_external_id),
        campaign_names.get(lead.campaign_external_id, lead.campaign_external_id),
        lead.form.name if lead.form is not None else "",
        word(note) if note else "",
        *(answers.get(question, "") for question in questions),
    )


def _local(moment: datetime, zone: ZoneInfo | None) -> datetime:
    """The moment on the owner's clock, or on UTC's when they gave no zone."""
    return moment.astimezone(zone if zone is not None else UTC)


def _px(chars: int) -> int:
    return chars * _PX_PER_CHAR + _PX_MARGIN


__all__ = [
    "FIXED_COLUMN_COUNT",
    "WORDS",
    "SheetBatch",
    "fixed_columns",
    "question_columns",
    "sheet_batch",
    "word",
]
