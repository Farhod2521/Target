"""A lead form's questions: Meta's own ticked, and the ones somebody wrote."""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.modules.ads.constants import (
    CUSTOM_QUESTION_PREFIX,
    MAX_CUSTOM_QUESTIONS,
    MAX_OPTIONS,
    NEW_ROW_PREFIX,
    QUESTION_TYPES,
)
from app.modules.leads.constants import QUESTION_LABELS

MAX_LABEL = 200
MAX_QUESTIONS = 10


class TypedQuestion(BaseModel):
    label: str = Field("", max_length=MAX_LABEL)
    options: list[str] = Field(default_factory=list)


class QuestionRow(BaseModel):
    """One row of the review screen's editor, in the order it stands.

    ``key`` is a kind already offered, or anything starting with ``new:``
    for a row typed in just now.
    """

    key: str
    label: str = Field("", max_length=MAX_LABEL)
    options: list[str] = Field(default_factory=list)
    text_only: bool = False


@dataclass(frozen=True, slots=True)
class QuestionEdit:
    """The shape ``save_questions`` takes."""

    kinds: list[str]
    added: list[str]
    options: dict[str, list[str]]
    labels: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    text_only: list[str] = field(default_factory=list)

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "kinds": self.kinds,
            "added": self.added,
            "options": self.options,
            "labels": self.labels,
            "order": self.order,
            "text_only": self.text_only,
        }


def _options(raw: list[str]) -> list[str]:
    return [item.strip() for item in raw if item.strip()][:MAX_OPTIONS]


def read_rows(rows: list[QuestionRow], *, offered: set[str]) -> QuestionEdit:
    """The rows as sent, with new ones renumbered in the order they stand."""
    seen: set[str] = set()
    edit = QuestionEdit(kinds=[], added=[], options={})
    for row in rows:
        token = row.key.strip()
        if token in seen or not (token in offered or token.startswith(NEW_ROW_PREFIX)):
            continue
        seen.add(token)
        label = row.label.strip()[:MAX_LABEL]
        if token.startswith(NEW_ROW_PREFIX):
            if not label:
                continue
            key = f"{NEW_ROW_PREFIX}{len(edit.added)}"
            edit.added.append(label)
        else:
            key = token
            edit.kinds.append(token)
            if label and token not in QUESTION_TYPES:
                edit.labels[token] = label
        edit.order.append(key)
        if values := _options(row.options):
            edit.options[key] = values
        if row.text_only:
            edit.text_only.append(key)
    return edit


def rows_error(edit: QuestionEdit) -> str:
    """Why these rows cannot be a form, or ``""``."""
    custom = [kind for kind in edit.order if kind not in QUESTION_TYPES]
    if len(custom) > MAX_CUSTOM_QUESTIONS:
        return f"Formada {MAX_CUSTOM_QUESTIONS} tadan ortiq o'z savolingiz bo'lmaydi."
    return ""


def new_form_questions(
    kinds: list[str], typed: list[TypedQuestion]
) -> list[dict[str, Any]]:
    """A new form's questions: Meta's ticked ones in its order, then typed."""
    built: list[dict[str, Any]] = [
        {"kind": kind, "label": str(QUESTION_LABELS.get(QUESTION_TYPES[kind], ""))}
        for kind in QUESTION_TYPES
        if kind in kinds
    ]
    for item in typed:
        label = item.label.strip()
        if not label:
            continue
        number = len(built) - sum(1 for q in built if q["kind"] in QUESTION_TYPES) + 1
        built.append(
            {
                "kind": f"{CUSTOM_QUESTION_PREFIX}{number}",
                "label": label,
                "options": _options(item.options),
            }
        )
    return built


__all__ = [
    "MAX_QUESTIONS",
    "QuestionEdit",
    "QuestionRow",
    "TypedQuestion",
    "new_form_questions",
    "read_rows",
    "rows_error",
]
