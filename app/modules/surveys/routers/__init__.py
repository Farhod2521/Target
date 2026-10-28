"""The survey dialog in the cabinet and the mini app.

Refusals: ``survey_answer_invalid`` carries ``problems`` keyed by question
id; ``survey_not_due`` means the survey closed or was answered elsewhere.
"""

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Db
from app.common.i18n import DEFAULT, LANGUAGES
from app.modules.accounts.models import User
from app.modules.surveys import services
from app.modules.surveys.constants import SNOOZE_SECONDS, ResponseChannel
from app.modules.surveys.exceptions import SurveyAnswerInvalid, SurveyNotDue
from app.modules.surveys.schemas import AnsweredOut, DueOut, LaterOut
from app.modules.surveys.selectors import due_survey

router = APIRouter(prefix="/surveys", tags=["surveys"])


class AnswerIn(BaseModel):
    survey: str = Field(description="The `survey_id` from `GET /surveys/due`.")
    answers: dict[str, list[str]] = Field(
        default_factory=dict,
        description="`{question id: [values]}`: typed text, option indexes, or "
        "the number picked.",
    )
    channel: Literal["web", "miniapp"] = Field(
        "web", description="`miniapp` when answered inside the Telegram Mini App."
    )


def _language(user: User) -> str:
    """The reader's language, as ``current_user`` activates it."""
    return user.language if user.language in LANGUAGES else DEFAULT


@router.get("/due", responses={200: {"model": DueOut}})
def due(db: Db, user: CurrentUser) -> dict[str, Any]:
    """The survey owed to this reader now, in their language, or null."""
    asked = due_survey(db, user=user, language=_language(user))
    if asked is None:
        return {"survey": None, "always": 0}
    return {"survey": asdict(asked), "always": len(asked.asked({}))}


@router.post("/answer", responses={200: {"model": AnsweredOut}})
def answer(body: AnswerIn, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Keep the answers, or refuse with what is wrong under each question."""
    try:
        services.answer_survey(
            db,
            owner=user,
            survey_id=body.survey,
            raw=body.answers,
            language=_language(user),
            channel=ResponseChannel(body.channel),
        )
    except SurveyAnswerInvalid:
        if due_survey(db, user=user, language=_language(user)) is None:
            raise SurveyNotDue from None
        raise
    db.commit()
    return {
        "title": "Rahmat!",
        "message": "Javoblaringizni o'qiymiz va platformani shunga qarab yaxshilaymiz.",
    }


@router.post("/later", responses={200: {"model": LaterOut}})
def later(user: CurrentUser) -> dict[str, Any]:
    """Not now: nothing is asked on any screen until the wait runs out."""
    services.snooze_survey(user=user)
    return {"ask_again_in": SNOOZE_SECONDS + 5}
