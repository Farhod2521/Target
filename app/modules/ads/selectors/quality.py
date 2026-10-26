"""Whether this account may buy leads on quality; free proposals; chat questions."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.presets import offered_goals
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    CHAT_QUESTIONS_DONE,
    CHAT_QUESTIONS_FAILED,
    CHAT_QUESTIONS_PENDING,
    CHAT_QUESTIONS_READING,
    LAUNCH_DRAFT_PROMPT,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.audit.constants import LLMCallStatus
from app.modules.audit.models import LLMCall
from core.targeting import clean_questions
from core.targeting.quality import (
    MIN_QUALIFIED_FOR_QUALITY,
    QUALITY_WINDOW_DAYS,
    is_available,
    is_lead_goal,
)


@dataclass(frozen=True, slots=True)
class QualityOffer:
    is_offered: bool
    is_reporting: bool
    qualified: int
    needed: int = MIN_QUALIFIED_FOR_QUALITY

    @property
    def short_by(self) -> int:
        return max(0, self.needed - self.qualified)


def quality_offer(
    db: Session, *, launch: CampaignLaunch, optimization_goal: str
) -> QualityOffer:
    """Whether this launch may be bought on the owner's own verdicts."""
    from app.modules.leads.selectors.reads import qualified_since, reporting_dataset

    if not is_lead_goal(optimization_goal):
        return QualityOffer(is_offered=False, is_reporting=False, qualified=0)
    dataset = reporting_dataset(db, owner=launch.owner, ad_account=launch.ad_account)
    if not dataset:
        return QualityOffer(is_offered=False, is_reporting=False, qualified=0)
    since = utcnow() - timedelta(days=QUALITY_WINDOW_DAYS)
    qualified = qualified_since(db, owner=launch.owner, since=since)
    return QualityOffer(
        is_offered=is_available(reporting=True, qualified_recently=qualified),
        is_reporting=True,
        qualified=qualified,
    )


def proposals_written(db: Session, *, owner: User) -> int:
    """Every proposal the AI has finished for this account, ever."""
    return int(
        db.scalar(
            select(func.count(LLMCall.id)).where(
                LLMCall.owner_id == owner.id,
                LLMCall.prompt_name == LAUNCH_DRAFT_PROMPT,
                LLMCall.status == str(LLMCallStatus.OK),
            )
        )
        or 0
    )


def catalogue_questions(db: Session, *, launch: CampaignLaunch, goal: str) -> list[str]:
    """The three questions the press puts in the rows before Claude answers."""
    from app.modules.businesses.selectors import business_for_page

    business = business_for_page(db, owner=launch.owner, page=launch.page)
    if business is None:
        return []
    for preset in offered_goals(provider=launch.provider, category=business.category):
        if preset.goal == goal:
            return list(preset.chat_questions)
    return []


def chat_question_reading(*, launch: CampaignLaunch) -> dict[str, Any]:
    raw = launch.answers.get(CHAT_QUESTIONS_READING)
    if not isinstance(raw, dict):
        return {"state": "", "questions": [], "token": ""}
    state = str(raw.get("state") or "")
    if state not in {CHAT_QUESTIONS_PENDING, CHAT_QUESTIONS_DONE}:
        state = CHAT_QUESTIONS_FAILED
    questions = raw.get("questions") or []
    return {
        "state": state,
        "questions": list(
            clean_questions(questions if isinstance(questions, list) else [])
        ),
        "token": str(raw.get("token") or ""),
    }
