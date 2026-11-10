"""Which survey answers ask for a specialist. Kept beside the survey, which
stays as it is; choosing one opens a Support ticket."""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError, NotFound
from app.modules.accounts.models import User
from app.modules.boards.models import SurveyHelpOption
from app.modules.surveys.constants import QuestionKind
from app.modules.surveys.models import SurveyQuestion


class QuestionNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("Savol topilmadi.")


class NotAChoice(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Faqat variantli savolga belgi qo'yiladi.")


class NoSuchOption(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Bunday variant yo'q.")


def _question(db: Session, question_id: uuid.UUID) -> SurveyQuestion:
    question = db.get(SurveyQuestion, question_id)
    if question is None:
        raise QuestionNotFound
    return question


def _text(option: Any) -> str:
    if isinstance(option, dict):
        for lang in ("uz", "ru", "en"):
            if option.get(lang):
                return str(option[lang])
        return next((str(v) for v in option.values() if v), "")
    return str(option)


def help_options(db: Session, *, question_id: uuid.UUID) -> dict[str, Any]:
    question = _question(db, question_id)
    marked = set(
        db.scalars(
            select(SurveyHelpOption.option_index).where(
                SurveyHelpOption.question_id == question.id
            )
        )
    )
    return {
        "question_id": str(question.id),
        "survey_id": str(question.survey_id),
        "kind": question.kind,
        "options": [
            {"index": index, "text": _text(option), "help": index in marked}
            for index, option in enumerate(question.options or [])
        ],
    }


def set_help_options(
    db: Session, *, question_id: uuid.UUID, indexes: list[int], user: User
) -> dict[str, Any]:
    """The question's specialist answers, all at once: what is not listed
    stops opening tickets."""
    question = _question(db, question_id)
    wanted = sorted(set(indexes))
    if wanted and question.kind != QuestionKind.CHOICE:
        raise NotAChoice
    if any(index < 0 or index >= len(question.options or []) for index in wanted):
        raise NoSuchOption
    db.execute(
        delete(SurveyHelpOption).where(SurveyHelpOption.question_id == question.id)
    )
    for index in wanted:
        db.add(
            SurveyHelpOption(
                question_id=question.id, option_index=index, set_by_id=user.id
            )
        )
    db.commit()
    return help_options(db, question_id=question.id)
