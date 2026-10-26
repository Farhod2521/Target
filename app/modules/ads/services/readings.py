"""Reading the owner's words into a goal or a row of the first step, and the
questions a chat advert should ask - each a press answered by a worker."""

import logging
from datetime import datetime
from typing import Any, TypeGuard
from uuid import UUID, uuid4

from llmkit import LLMError, LLMResult, render
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import throttle
from app.common.config import settings
from app.common.db import on_commit
from app.common.exceptions import LLMUnavailable
from app.common.llm import MECHANICAL, claude, model_for, prompts
from app.common.presets import offered_goals
from app.modules.ads.constants import (
    CHAT_QUESTION_SUGGESTIONS_PER_HOUR,
    CHAT_QUESTIONS_DONE,
    CHAT_QUESTIONS_FAILED,
    CHAT_QUESTIONS_PENDING,
    CHAT_QUESTIONS_READING,
    CLOSED_REASONS,
    GOAL_BY_AI,
    GOAL_FAILED,
    GOAL_PENDING,
    GOAL_READING,
    GOAL_READINGS_PER_HOUR,
    LAUNCH_RELATED_TYPE,
    READING_V3,
)
from app.modules.ads.exceptions import (
    ChatQuestionsExhausted,
    GoalReadingsExhausted,
    UnknownGoal,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.goals import launch_category, legacy_plan_goals
from app.modules.ads.selectors.plan_picker import account_facts
from app.modules.ads.services.launch import save_answers
from app.modules.audit.constants import LLMPurpose
from app.modules.billing.exceptions import NoEntitlement
from app.modules.businesses.models import Business
from core.agent import (
    ChatQuestions,
    ChoiceReading,
    GoalChoice,
    GoalIntent,
    GoalReading,
    read_goal,
    read_goal_choice,
)
from core.agent.goal_table import render_rows
from core.targeting import (
    OUTCOMES,
    Offer,
    Preset,
    clean_questions,
    closed_by,
    default_offer,
    listed_for,
    offer,
    outcome_default,
)

logger = logging.getLogger(__name__)
PROMPT = "goal_intent"
GOAL_PROMPT_VERSION = "v2"
ROW_PROMPT_VERSION = "v5"
GOAL_THROTTLE = "ads:goal-reading"
CHAT_PROMPT = "chat_questions"
CHAT_THROTTLE = "ads:chat-questions"
HOUR_SECONDS = 3600


def _business(db: Session, launch: CampaignLaunch) -> Business | None:
    from app.modules.businesses.selectors import business_for_page

    return business_for_page(db, owner=launch.owner, page=launch.page)


def _locked(db: Session, launch: CampaignLaunch) -> CampaignLaunch | None:
    return db.scalar(
        select(CampaignLaunch)
        .where(CampaignLaunch.id == launch.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _record(db: Session, launch: CampaignLaunch, result: LLMResult[Any]) -> None:
    from app.modules.audit.services import record_llm_result

    record_llm_result(
        db,
        owner=launch.owner,
        purpose=LLMPurpose.ONBOARDING,
        result=result,
        related_type=LAUNCH_RELATED_TYPE,
        related_id=launch.id,
    )
    db.commit()


def _record_failure(
    db: Session, launch: CampaignLaunch, exc: LLMError, *, prompt: str, version: str
) -> None:
    from app.modules.audit.services import record_llm_error

    record_llm_error(
        db,
        owner=launch.owner,
        purpose=LLMPurpose.ONBOARDING,
        exc=exc,
        prompt_name=prompt,
        prompt_version=version,
        model=model_for(MECHANICAL),
        currency=str(settings.anthropic_price_currency),
        related_type=LAUNCH_RELATED_TYPE,
        related_id=launch.id,
    )
    db.commit()


def ask_goal_intent[T: BaseModel](
    *, version: str, schema: type[T], variables: dict[str, object]
) -> LLMResult[T]:
    """The one call behind both pickers, at a pinned prompt version."""
    template, pinned = prompts().get(PROMPT, version=version)
    with claude(tier=MECHANICAL) as client:
        return client.structured(
            prompt=render(template, variables),
            schema=schema,
            prompt_name=PROMPT,
            prompt_version=pinned,
        )


# -- the rows of the three-question picker --------------------------------------------


def visible_rows(
    db: Session, launch: CampaignLaunch, *, keep: str = ""
) -> tuple[Offer, ...]:
    category = launch_category(db, launch=launch)
    if not category:
        return ()
    goals = {
        preset.goal
        for preset in offered_goals(provider=launch.provider, category=category)
    }
    return tuple(
        row
        for spec in OUTCOMES
        for row in listed_for(provider=launch.provider, outcome=spec.key, keep=keep)
        if row.goal in goals
    )


def choose_row(
    db: Session, *, launch: CampaignLaunch, key: str, by: str, text: str
) -> None:
    """Settle the row with no call: a ready phrase, or an option pressed."""
    rows = {row.key: row for row in visible_rows(db, launch)}
    found = rows.get(key) or _default_for_goal(launch, key, rows)
    if found is None:
        raise UnknownGoal
    save_answers(db, launch=launch, goal_text=text, goal_reading=_found(found, by=by))


def read_rows(
    db: Session, *, launch: CampaignLaunch, business: Business, text: str
) -> tuple[LLMResult[GoalChoice], ChoiceReading]:
    rows = visible_rows(db, launch)
    facts = account_facts(db, launch=launch)
    closed = {
        row.key: str(CLOSED_REASONS.get(reasons[0], reasons[0]))
        for row in rows
        if (reasons := closed_by(row, facts))
    }
    defaults = frozenset(
        found.key
        for spec in OUTCOMES
        if (found := outcome_default(provider=launch.provider, outcome=spec.key))
    )
    from app.modules.businesses.selectors import category_label

    result = ask_goal_intent(
        version=ROW_PROMPT_VERSION,
        schema=GoalChoice,
        variables={
            "business_name": business.name,
            "business_category": category_label(business),
            "rows": render_rows(offers=rows, defaults=defaults, closed=closed),
            "text": text,
        },
    )
    reading = read_goal_choice(result.value, rows=[row.key for row in rows], text=text)
    return result, reading


def row_reading(reading: ChoiceReading, *, launch: CampaignLaunch) -> dict[str, Any]:
    found = offer(provider=launch.provider, key=reading.row) if reading.row else None
    if reading.state == "unclear" or found is None:
        return {"state": "unclear", "by": GOAL_BY_AI, "v": READING_V3}
    return _found(found, by=GOAL_BY_AI) | {
        "state": reading.state,
        "alternatives": list(reading.alternatives),
        "quote": reading.quote,
    }


def _found(row: Offer, *, by: str) -> dict[str, Any]:
    return {
        "state": "found",
        "row": row.key,
        "goals": [row.goal],
        "alternatives": [],
        "quote": "",
        "by": by,
        "v": READING_V3,
    }


def _default_for_goal(
    launch: CampaignLaunch, goal: str, rows: dict[str, Offer]
) -> Offer | None:
    found = default_offer(provider=launch.provider, goal=goal)
    return found if found is not None and found.key in rows else None


# -- the goal said in words ----------------------------------------------------------


def request_goal_reading(
    db: Session, *, launch: CampaignLaunch, text: str, now: datetime, version: int = 0
) -> None:
    """Save the words and ask for them to be read. Caller commits."""
    from app.modules.ads.tasks import detect_goal_task

    if not throttle.hit(
        bucket=GOAL_THROTTLE,
        key=str(launch.owner_id),
        limit=GOAL_READINGS_PER_HOUR,
        window_seconds=HOUR_SECONDS,
    ):
        raise GoalReadingsExhausted
    token = uuid4().hex
    launch_id = str(launch.id)
    save_answers(
        db,
        launch=launch,
        goal_text=text,
        goal_reading={
            "state": GOAL_PENDING,
            "token": token,
            "text": text,
            "asked_at": now.isoformat(),
            **({"v": version} if version else {}),
        },
    )
    on_commit(db, lambda: detect_goal_task.delay(launch_id, token))


def choose_goal(
    db: Session, *, launch: CampaignLaunch, goal: str, by: str, text: str
) -> None:
    if goal not in {preset.goal for preset in _offered(db, launch)}:
        raise UnknownGoal
    save_answers(
        db,
        launch=launch,
        goal_text=text,
        goal_reading={
            "state": "found",
            "goals": [goal],
            "by": by,
            "quote": "",
            "text": text,
        },
    )


def detect_goal(db: Session, *, launch_id: UUID | str, token: str) -> str:
    """The worker half. Returns a word for the task log."""
    from app.modules.billing.services import require_preparation

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    asked = launch.answers.get(GOAL_READING)
    if not _is_this_reading(asked, token=token):
        return "superseded"
    text = str(asked.get("text") or "")
    business = _business(db, launch)
    offered = _offered(db, launch)
    if business is None or not offered:
        return _settle(db, launch, token=token, reading=None)
    is_v3 = asked.get("v") == READING_V3
    try:
        require_preparation(db, owner=launch.owner)
        if is_v3:
            found, choice = read_rows(db, launch=launch, business=business, text=text)
            _record(db, launch, found)
            return _write(
                db, launch, token=token, settled=row_reading(choice, launch=launch)
            )
        result = _ask_goals(business=business, offered=offered, text=text)
    except NoEntitlement:
        return _settle(db, launch, token=token, reading=None)
    except LLMUnavailable:
        logger.error("goal_reading_unavailable", extra={"launch": str(launch.id)})
        return _settle(db, launch, token=token, reading=None)
    except LLMError as exc:
        _record_failure(
            db,
            launch,
            exc,
            prompt=PROMPT,
            version=ROW_PROMPT_VERSION if is_v3 else GOAL_PROMPT_VERSION,
        )
        return _settle(db, launch, token=token, reading=None)
    _record(db, launch, result)
    reading = read_goal(
        result.value, offered=[preset.goal for preset in offered], text=text
    )
    return _settle(db, launch, token=token, reading=reading)


def _offered(db: Session, launch: CampaignLaunch) -> tuple[Preset, ...]:
    category = launch_category(db, launch=launch)
    if not category:
        return ()
    return legacy_plan_goals(provider=launch.provider, category=category)


def _ask_goals(
    *, business: Business, offered: tuple[Preset, ...], text: str
) -> LLMResult[GoalIntent]:
    from app.modules.businesses.selectors import category_label

    return ask_goal_intent(
        version=GOAL_PROMPT_VERSION,
        schema=GoalIntent,
        variables={
            "business_name": business.name,
            "business_category": category_label(business),
            "offered_goals": "\n".join(
                f"- `{preset.goal}` - {preset.label}" for preset in offered
            ),
            "text": text,
        },
    )


def _settle(
    db: Session, launch: CampaignLaunch, *, token: str, reading: GoalReading | None
) -> str:
    settled: dict[str, Any] = (
        {"state": GOAL_FAILED}
        if reading is None
        else {
            "state": reading.state,
            "goals": list(reading.goals),
            "quote": reading.quote,
            "by": GOAL_BY_AI,
        }
    )
    return _write(db, launch, token=token, settled=settled)


def _write(
    db: Session, launch: CampaignLaunch, *, token: str, settled: dict[str, Any]
) -> str:
    row = _locked(db, launch)
    asked = row.answers.get(GOAL_READING) if row is not None else None
    if row is None or not _is_this_reading(asked, token=token):
        db.rollback()
        return "superseded"
    kept = {"v": asked["v"]} if "v" in asked else {}
    save_answers(
        db,
        launch=row,
        goal_reading=kept | settled | {"token": token, "text": asked.get("text", "")},
    )
    db.commit()
    return str(settled["state"])


def _is_this_reading(asked: object, *, token: str) -> TypeGuard[dict[str, Any]]:
    return (
        isinstance(asked, dict)
        and asked.get("token") == token
        and asked.get("state") == GOAL_PENDING
    )


# -- the questions of a chat advert ---------------------------------------------------


def request_chat_questions(
    db: Session, *, launch: CampaignLaunch, now: datetime
) -> None:
    """Mark a suggestion pending and ask for it. Caller commits."""
    from app.modules.ads.tasks import suggest_chat_questions_task

    if not throttle.hit(
        bucket=CHAT_THROTTLE,
        key=str(launch.owner_id),
        limit=CHAT_QUESTION_SUGGESTIONS_PER_HOUR,
        window_seconds=HOUR_SECONDS,
    ):
        raise ChatQuestionsExhausted
    token = uuid4().hex
    launch_id = str(launch.id)
    save_answers(
        db,
        launch=launch,
        chat_questions_reading={
            "state": CHAT_QUESTIONS_PENDING,
            "token": token,
            "asked_at": now.isoformat(),
        },
    )
    on_commit(db, lambda: suggest_chat_questions_task.delay(launch_id, token))


def suggest_chat_questions(db: Session, *, launch_id: UUID | str, token: str) -> str:
    """The worker half. Returns a word for the task log."""
    from app.modules.ads.services.proposal import prompt_variables
    from app.modules.billing.services import require_preparation

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    if not _is_this_press(launch.answers.get(CHAT_QUESTIONS_READING), token=token):
        return "superseded"
    failed = {"state": CHAT_QUESTIONS_FAILED}
    business = _business(db, launch)
    if business is None:
        return _write_chat(db, launch, token=token, settled=failed)
    try:
        require_preparation(db, owner=launch.owner)
        template, version = prompts().get(CHAT_PROMPT)
        with claude(tier=MECHANICAL) as client:
            result = client.structured(
                prompt=render(
                    template, prompt_variables(db, launch=launch, business=business)
                ),
                schema=ChatQuestions,
                prompt_name=CHAT_PROMPT,
                prompt_version=version,
            )
    except NoEntitlement:
        return _write_chat(db, launch, token=token, settled=failed)
    except LLMUnavailable:
        logger.error("chat_questions_unavailable", extra={"launch": str(launch.id)})
        return _write_chat(db, launch, token=token, settled=failed)
    except LLMError as exc:
        _record_failure(
            db, launch, exc, prompt=CHAT_PROMPT, version=prompts().latest(CHAT_PROMPT)
        )
        return _write_chat(db, launch, token=token, settled=failed)
    _record(db, launch, result)
    questions = list(clean_questions(result.value.questions))
    if not questions:
        return _write_chat(db, launch, token=token, settled=failed)
    return _write_chat(
        db,
        launch,
        token=token,
        settled={"state": CHAT_QUESTIONS_DONE, "questions": questions},
    )


def _is_this_press(asked: object, *, token: str) -> bool:
    return isinstance(asked, dict) and asked.get("token") == token


def _write_chat(
    db: Session, launch: CampaignLaunch, *, token: str, settled: dict[str, Any]
) -> str:
    row = _locked(db, launch)
    if row is None or not _is_this_press(
        row.answers.get(CHAT_QUESTIONS_READING), token=token
    ):
        db.rollback()
        return "superseded"
    save_answers(db, launch=row, chat_questions_reading=settled | {"token": token})
    db.commit()
    return str(settled["state"])
