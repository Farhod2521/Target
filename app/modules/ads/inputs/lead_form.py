"""The first screen's lead-form picker: an existing form, or a new one."""

from typing import Any

from pydantic import BaseModel, Field

from app.modules.ads.constants import LEAD_FORM_NAME_MAX, QUESTION_TYPES
from app.modules.ads.inputs import Problems
from app.modules.ads.inputs.ending import EndingIn, check_ending
from app.modules.ads.inputs.questions import (
    MAX_QUESTIONS,
    TypedQuestion,
    new_form_questions,
)
from core.leads.ending import FormEnding

DEFAULT_KINDS = ("full_name", "phone")
FULL_NAME = "full_name"
NAME_PARTS = frozenset({"first_name", "last_name"})


class LeadFormPickIn(BaseModel):
    goal: str = ""
    lead_form: str = Field("", max_length=128, description="An existing form's id.")
    name: str = Field("", max_length=LEAD_FORM_NAME_MAX)
    kinds: list[str] = Field(default_factory=list, description="Meta's own questions.")
    typed: list[TypedQuestion] = Field(default_factory=list)
    ending: EndingIn | None = None


def check_pick(
    body: LeadFormPickIn,
    *,
    default_name: str,
    taken_names: frozenset[str],
    region: str,
    default_title: str,
) -> tuple[str, list[dict[str, Any]] | None, str, FormEnding | None]:
    """``(external_id, questions, name, ending)`` for ``choose_lead_form``."""
    if body.lead_form:
        return body.lead_form, None, "", None
    problems = Problems()
    unknown = [kind for kind in body.kinds if kind not in QUESTION_TYPES]
    if unknown:
        problems.add("kinds", "Savollar ro'yxatidan tanlang.")
    questions = new_form_questions(body.kinds, body.typed)
    kinds = {question["kind"] for question in questions}
    if not questions:
        problems.add("", "Kamida bitta savol tanlang.")
    elif len(questions) > MAX_QUESTIONS:
        problems.add("", f"Bitta formada {MAX_QUESTIONS} tadan ortiq savol bo'lmaydi.")
    elif FULL_NAME in kinds and kinds & NAME_PARTS:
        problems.add(
            "",
            "«Ism va familiya» bilan «Faqat ism» yoki «Familiya» birga "
            "tanlanmaydi — bittasini qoldiring.",
        )
    name = body.name.strip() or default_name
    if name.casefold() in {item.casefold() for item in taken_names}:
        problems.add("name", "Bu nomli forma sahifangizda bor. Boshqa nom yozing.")
    ending = check_ending(
        body.ending, region=region, default_title=default_title, problems=problems
    )
    problems.refuse()
    return "", questions, name, ending


__all__ = ["DEFAULT_KINDS", "LeadFormPickIn", "check_pick"]
