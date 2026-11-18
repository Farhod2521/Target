"""The office writing the known problems the assistant searches."""

import re
import uuid
from datetime import datetime
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import on_commit, utcnow
from app.common.exceptions import Conflict, InputRefused, NotFound
from app.modules.accounts.models import User
from app.modules.assistant.constants import HELP_LANGUAGES, Translation
from app.modules.assistant.models import HelpArticle

CODE: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
FIELDS: Final = (
    "problem_uz",
    "problem_ru",
    "problem_en",
    "steps_uz",
    "steps_ru",
    "steps_en",
    "keywords",
)
PROBLEM_CHARS: Final = 255
STEPS_CHARS: Final = 4000


class ArticleMissing(NotFound):
    def __init__(self) -> None:
        super().__init__("Maqola topilmadi.")


def articles(db: Session, *, query: str = "") -> list[HelpArticle]:
    """Every article, published or not, in the order the office set."""
    statement = select(HelpArticle).order_by(
        HelpArticle.position, HelpArticle.created_at
    )
    if query.strip():
        like = f"%{query.strip().lower()}%"
        statement = statement.where(
            func.lower(
                HelpArticle.code
                + " "
                + HelpArticle.problem_uz
                + " "
                + HelpArticle.problem_ru
                + " "
                + HelpArticle.keywords
            ).like(like)
        )
    return list(db.scalars(statement))


def article(db: Session, pk: uuid.UUID) -> HelpArticle:
    found = db.get(HelpArticle, pk)
    if found is None:
        raise ArticleMissing
    return found


def save_article(
    db: Session,
    *,
    fields: dict[str, Any],
    now: datetime,
    row: HelpArticle | None = None,
    actor: User | None = None,
    translate_from: str = "",
    commit: bool = True,
) -> HelpArticle:
    """Create or change one article; refused field by field. An article is
    published only with its Uzbek problem and steps written.

    ``translate_from`` is the language the office wrote: a worker then
    writes every other language this save did not change itself."""
    clean = _checked(db, fields=fields, row=row, source=translate_from)
    targets = _targets(clean, row=row, source=translate_from)
    target = row or HelpArticle(id=uuid.uuid4(), created_at=now)
    for name, value in clean.items():
        setattr(target, name, value)
    target.updated_at = now
    target.translation = (
        Translation.TRANSLATING if targets and actor is not None else Translation.NONE
    )
    if row is None:
        db.add(target)
    db.flush()
    if targets and actor is not None:
        from app.modules.assistant.tasks import translate_article_task

        article_id, actor_id = str(target.id), str(actor.id)
        on_commit(
            db,
            lambda: translate_article_task.delay(
                article_id, actor_id, translate_from, targets
            ),
        )
    if commit:
        db.commit()
    return target


def _targets(
    clean: dict[str, Any], *, row: HelpArticle | None, source: str
) -> list[str]:
    """The languages to write from ``source``: each one whose words this
    save left as they were."""
    if source not in HELP_LANGUAGES:
        return []
    if not (clean[f"problem_{source}"] and clean[f"steps_{source}"]):
        return []
    return [
        code
        for code in HELP_LANGUAGES
        if code != source
        and all(
            clean[f"{name}_{code}"] == (getattr(row, f"{name}_{code}") if row else "")
            for name in ("problem", "steps")
        )
    ]


def delete_article(db: Session, *, row: HelpArticle) -> None:
    from app.modules.assistant.services.gaps import release_article

    release_article(db, article_id=row.id)
    db.delete(row)
    db.commit()


def article_out(row: HelpArticle) -> dict[str, Any]:
    from app.modules.assistant.services.translate import shown

    return {
        "translation": shown(row.translation, since=row.updated_at, now=utcnow()),
        "id": str(row.id),
        "code": row.code,
        **{name: getattr(row, name) for name in FIELDS},
        "is_published": row.is_published,
        "position": row.position,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _checked(
    db: Session, *, fields: dict[str, Any], row: HelpArticle | None, source: str = ""
) -> dict[str, Any]:
    problems: dict[str, str] = {}
    clean: dict[str, Any] = {}
    code = str(fields.get("code") or (row.code if row else "")).strip().lower()
    if not code:
        # The office names a problem, not a code: one is made for it.
        code = f"javob-{uuid.uuid4().hex[:10]}"
    if not CODE.match(code):
        problems["code"] = (
            "Kod: kichik lotin harflari, raqam, '-' yoki '_' (2-64 belgi)."
        )
    else:
        taken = db.scalar(
            select(HelpArticle.id).where(
                HelpArticle.code == code,
                *([HelpArticle.id != row.id] if row is not None else []),
            )
        )
        if taken is not None:
            problems["code"] = "Bu kod band."
    clean["code"] = code
    for name in FIELDS:
        value = fields.get(name, getattr(row, name) if row else "")
        text = "\n".join(
            line.rstrip() for line in str(value or "").strip().splitlines()
        )
        limit = PROBLEM_CHARS if name.startswith("problem") else STEPS_CHARS
        if len(text) > limit:
            problems[name] = f"Eng ko'pi {limit} belgi."
        clean[name] = text
    clean["position"] = int(fields.get("position", row.position if row else 0) or 0)
    published = bool(fields.get("is_published", row.is_published if row else False))
    # Written in another language and on its way into Uzbek: the Uzbek is
    # there before anybody is shown it, or the search falls back to none.
    coming = source in HELP_LANGUAGES and bool(
        clean[f"problem_{source}"] and clean[f"steps_{source}"]
    )
    if published and not (clean["problem_uz"] and clean["steps_uz"]) and not coming:
        problems["is_published"] = (
            "Chop etishdan oldin o'zbekcha muammo va qadamlarni yozing."
        )
    clean["is_published"] = published
    if problems:
        raise InputRefused(problems)
    return clean


__all__ = [
    "ArticleMissing",
    "Conflict",
    "article",
    "article_out",
    "articles",
    "delete_article",
    "save_article",
]
