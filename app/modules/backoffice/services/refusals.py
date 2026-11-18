"""The office's words for a refusal, which every owner then reads."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.modules.accounts.models import User
from app.modules.assistant.constants import Translation
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
    translate_from: str = "",
) -> RefusalAnswer:
    """Save these languages, and mark the answer checked: a person has read it.

    Saved as it stands, that is the whole check, and a held answer starts to
    show. A retired version is revived the same way. The office's version is never
    among the stale ones, so no later answer from Claude can replace it.

    ``translate_from`` is the language the office wrote: a worker then
    writes every other language this save did not carry itself, and the
    row says so until it has (``translation``).
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
    source = REFUSAL_ANSWER_FIELDS.get(translate_from, "")
    targets = (
        [
            language
            for language, field in REFUSAL_ANSWER_FIELDS.items()
            if field != source and field not in answers
        ]
        if source and merged[source]
        else []
    )
    row.translation = Translation.TRANSLATING if targets else Translation.NONE
    if targets:
        from app.modules.assistant.tasks import translate_refusal_task

        answer_id, actor_id = str(row.id), str(actor.id)
        on_commit(
            db,
            lambda: translate_refusal_task.delay(
                answer_id, actor_id, translate_from, targets
            ),
        )
    record(
        db,
        customer=actor,
        actor=actor,
        kind=ActionKind.REFUSAL_EDITED,
        detail={
            "key": row.key,
            "changed": changed,
            **({"translated": targets} if targets else {}),
        },
    )
    db.flush()
    return row


__all__ = ["edit_refusal_answer"]
