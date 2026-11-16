"""A chat advert's greeting and questions, kept under a name.

A template belongs to the owner and the page the advert is for: a greeting
names the business, so one page's templates are not offered on another.
Saving under a name already there writes over that template.
"""

import uuid
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.exceptions import NotFound
from app.modules.accounts.models import User
from app.modules.ads.inputs import Problems
from app.modules.ads.models import CampaignLaunch, ChatTemplate
from core.targeting import (
    MAX_ANSWER_CHARS,
    MAX_CHAT_QUESTIONS,
    MAX_GREETING_CHARS,
    clean_answered,
)
from core.targeting.chat import MAX_QUESTION_CHARS

MAX_TEMPLATES: Final = 20
MAX_NAME_CHARS: Final = 40


def _here(launch: CampaignLaunch):  # type: ignore[no-untyped-def]
    page = (
        ChatTemplate.page_id.is_(None)
        if launch.page_id is None
        else ChatTemplate.page_id == launch.page_id
    )
    return ChatTemplate.owner_id == launch.owner_id, page


def templates_for(db: Session, *, launch: CampaignLaunch) -> list[ChatTemplate]:
    """This page's templates, the one saved last first."""
    return list(
        db.scalars(
            select(ChatTemplate)
            .where(*_here(launch))
            .order_by(ChatTemplate.updated_at.desc(), ChatTemplate.id)
        )
    )


def save_template(
    db: Session,
    *,
    launch: CampaignLaunch,
    name: str,
    welcome_text: str,
    questions: list[str],
    answers: list[str],
) -> ChatTemplate:
    """Keep the greeting and questions under ``name``; the same name (in any
    letter case) is written over. Refuses field by field."""
    problems = Problems()
    name = " ".join(name.split())
    welcome = welcome_text.strip()
    asked, replies = clean_answered(questions, answers)
    kept = list(asked)
    if not name:
        problems.add("name", "Shablonga nom bering.")
    elif len(name) > MAX_NAME_CHARS:
        problems.add("name", f"Nom {MAX_NAME_CHARS} belgidan oshmasin.")
    if not welcome:
        problems.add("welcome_text", "Avval «Suhbat qanday boshlansin?» ni yozing.")
    elif len(welcome) > MAX_GREETING_CHARS:
        problems.add(
            "welcome_text", f"Salom matni {MAX_GREETING_CHARS} belgidan oshmasin."
        )
    if len(kept) > MAX_CHAT_QUESTIONS:
        problems.add(
            "chat_questions",
            f"Ko'pi bilan {MAX_CHAT_QUESTIONS} ta savol qo'shish mumkin.",
        )
    elif any(len(question) > MAX_QUESTION_CHARS for question in kept):
        problems.add(
            "chat_questions", f"Har bir savol {MAX_QUESTION_CHARS} belgidan oshmasin."
        )
    if any(len(reply) > MAX_ANSWER_CHARS for reply in replies):
        problems.add(
            "chat_answers", f"Har bir avto javob {MAX_ANSWER_CHARS} belgidan oshmasin."
        )
    problems.refuse()

    # One save at a time per owner: two presses must not make two of a name.
    db.execute(select(User.id).where(User.id == launch.owner_id).with_for_update())
    found = db.scalar(
        select(ChatTemplate).where(
            *_here(launch), func.lower(ChatTemplate.name) == name.lower()
        )
    )
    if found is None:
        count = db.scalar(
            select(func.count()).select_from(ChatTemplate).where(*_here(launch))
        )
        if (count or 0) >= MAX_TEMPLATES:
            problems.add(
                "name",
                f"Ko'pi bilan {MAX_TEMPLATES} ta shablon saqlanadi. "
                "Keraksizini o'chiring yoki bor nom bilan saqlang.",
            )
            problems.refuse()
        found = ChatTemplate(owner_id=launch.owner_id, page_id=launch.page_id)
        db.add(found)
    found.name = name
    found.welcome_text = welcome
    found.questions = kept
    found.answers = list(replies) if any(replies) else []
    db.flush()
    return found


def delete_template(
    db: Session, *, launch: CampaignLaunch, template_id: uuid.UUID
) -> None:
    found = db.scalar(
        select(ChatTemplate).where(*_here(launch), ChatTemplate.id == template_id)
    )
    if found is None:
        raise NotFound("Shablon topilmadi.")
    from app.modules.ads.services.chat_template_flows import take_off_page

    take_off_page(db, launch=launch, template=found)
    db.delete(found)
    db.flush()


__all__ = [
    "MAX_NAME_CHARS",
    "MAX_TEMPLATES",
    "delete_template",
    "save_template",
    "templates_for",
]
