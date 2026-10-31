"""The office's words for a refusal, which every owner then reads."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import RefusalAnswerEmpty
from app.modules.backoffice.services.journal import record
from app.modules.chat.constants import REFUSAL_ANSWER_FIELDS, REFUSAL_OFFICE_VERSION
from app.modules.chat.models import RefusalAnswer


def edit_refusal_answer(
    db: Session,
    *,
    actor: User,
    row: RefusalAnswer,
    answers: dict[str, str],
    now: datetime,
) -> RefusalAnswer:
    """Save these languages, and show the answer: a person has now read it.

    A retired version is revived the same way. The office's version is never
    among the stale ones, so no later answer from Claude can replace it.
    """
    fields = REFUSAL_ANSWER_FIELDS.values()
    merged = {
        field: answers.get(field, getattr(row, field)).strip() for field in fields
    }
    if not any(merged.values()):
        raise RefusalAnswerEmpty
    changed = sorted(field for field in fields if merged[field] != getattr(row, field))
    for field, text in merged.items():
        setattr(row, field, text)
    row.held = False
    row.prompt_version = REFUSAL_OFFICE_VERSION
    row.edited_at = now
    record(
        db,
        customer=actor,
        actor=actor,
        kind=ActionKind.REFUSAL_EDITED,
        detail={"key": row.key, "changed": changed},
    )
    db.flush()
    return row


__all__ = ["edit_refusal_answer"]
