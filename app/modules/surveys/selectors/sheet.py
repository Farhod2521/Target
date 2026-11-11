"""One survey's answers as a table: a customer per row, a question per column.

A question the customer was not asked is an empty cell, not a word. A
half-finished answer is a row too, marked «Chala».
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.common.timezone import localtime
from app.common.xlsx import Cell, Column
from app.modules.surveys.constants import RESPONSE_CHANNEL_LABELS, QuestionKind
from app.modules.surveys.models import Survey, SurveyQuestion, SurveyResponse
from app.modules.surveys.selectors.office import office_language, questions_of, shown

QUESTION_WIDTH = 32


@dataclass(frozen=True, slots=True)
class SurveySheet:
    columns: list[Column]
    rows: list[list[Cell]]


def _cell(row: SurveyQuestion, item: dict[str, Any] | None, lang: str) -> Cell:
    if item is None:
        return None
    if row.kind == QuestionKind.NUMBER:
        number = item.get("number")
        return number if isinstance(number, int) else None
    return shown(row, item, lang) or None


def survey_sheet(db: Session, *, survey: Survey) -> SurveySheet:
    """Every answer, oldest first."""
    lang = office_language(survey)
    questions = questions_of(db, survey.id)
    answers = db.scalars(
        select(SurveyResponse)
        .options(joinedload(SurveyResponse.owner))
        .where(SurveyResponse.survey_id == survey.id)
        .order_by(SurveyResponse.created_at)
    )
    columns = [
        Column("Ism", 24),
        Column("Email", 28),
        Column("Telefon", 18),
        Column("Qayerdan", 12),
        Column("Holati", 12),
        Column("Sana", 17),
    ] + [
        Column(f"{row.position}. {row.text.get(lang, '')}", QUESTION_WIDTH)
        for row in questions
    ]
    rows: list[list[Cell]] = []
    for response in answers:
        owner = response.owner
        said = {str(item.get("question")): item for item in response.answers}
        rows.append(
            [
                owner.full_name or None,
                owner.email,
                owner.phone or None,
                str(RESPONSE_CHANNEL_LABELS.get(response.channel, response.channel)),
                "Tugatgan" if response.completed_at else "Chala",
                f"{localtime(response.completed_at or response.created_at):%d.%m.%Y %H:%M}",
                *[_cell(row, said.get(str(row.id)), lang) for row in questions],
            ]
        )
    return SurveySheet(columns=columns, rows=rows)
