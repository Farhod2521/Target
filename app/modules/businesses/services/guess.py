"""Guessing a business's kind from what its page says about itself.

One short call, made by a worker when a profile was written for a page
nobody described (``services.auto_profile``). What comes back is kept as a
guess: the direction and the narrower kind are marked ``guessed``, the name
replaces the page's raw one only when every word of it stands on the page,
and the sentence about what the business does waits on the business's list
for a yes. A business whose kind somebody already said is left alone.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from llmkit import LLMError, LLMResult, render
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.exceptions import LLMUnavailable
from app.common.llm import MECHANICAL, claude, prompts
from app.modules.audit.constants import LLMPurpose
from app.modules.audit.services import record_llm_result
from app.modules.businesses.constants import KnowledgeSource, TypeState
from app.modules.businesses.exceptions import BadKnowledgeChange, BadSubtype
from app.modules.businesses.models import Business, BusinessCategory, BusinessSubtype
from app.modules.businesses.selectors import offered_directions
from app.modules.businesses.selectors.knowledge import known
from app.modules.businesses.services import knowledge, subtypes
from app.modules.businesses.services.kinds import set_kind
from app.modules.integrations.models import PageAccount
from core.business_kind import KindGuess

logger = logging.getLogger(__name__)

PROMPT = "business_kind"
TURN = "Decide what kind of business this page belongs to."
RELATED_TYPE = "business"
# How many narrower kinds the model is shown, so it reuses one of them.
SUBTYPES_SHOWN = 150
BIO_CHARS = 600
NO_SUBTYPES = "None yet."


@dataclass(frozen=True, slots=True)
class Guessed:
    """What one guess changed."""

    direction: str = ""
    subtype: str = ""
    renamed: bool = False
    proposed_about: bool = False


def page_words(page: PageAccount) -> str:
    """Everything the page says about itself, one labelled line each."""
    said = (
        ("Facebook page name", page.name),
        ("Instagram name", page.instagram_name),
        ("Instagram username", page.instagram_username),
        ("Instagram bio", str(page.instagram_biography or "")[:BIO_CHARS]),
        ("Website", page.instagram_website),
        ("City", page.location_city),
        ("Business portfolio name", page.business_name),
    )
    return "\n".join(
        f"{label}: {' '.join(str(value).split())}" for label, value in said if value
    )


def _directions(rows: list[BusinessCategory]) -> str:
    return "\n".join(f"- {row.key} - {row.label_uz}" for row in rows)


def _subtypes(db: Session, rows: list[BusinessCategory]) -> str:
    by_id = {row.id: row.key for row in rows}
    found = db.execute(
        select(BusinessSubtype.direction_id, BusinessSubtype.name)
        .where(
            BusinessSubtype.is_active.is_(True),
            BusinessSubtype.merged_into_id.is_(None),
            BusinessSubtype.direction_id.in_(by_id),
        )
        .order_by(BusinessSubtype.is_checked.desc(), BusinessSubtype.created_at)
        .limit(SUBTYPES_SHOWN)
    ).all()
    if not found:
        return NO_SUBTYPES
    return "\n".join(f"- {by_id[direction_id]}: {name}" for direction_id, name in found)


def ask(db: Session, *, page: PageAccount) -> LLMResult[KindGuess] | None:
    """The model's guess for one page, or nothing when the page says
    nothing. Raises whatever ``llmkit`` raises; writes nothing."""
    words = page_words(page)
    if not words:
        return None
    rows = offered_directions(db)
    template, version = prompts().get(PROMPT)
    with claude(tier=MECHANICAL) as client:
        return client.structured(  # type: ignore[no-any-return]
            prompt=TURN,
            system=render(
                template,
                {
                    "page": words,
                    "directions": _directions(rows),
                    "subtypes": _subtypes(db, rows),
                },
            ),
            schema=KindGuess,
            prompt_name=PROMPT,
            prompt_version=version,
        )


def _on_the_page(name: str, page: PageAccount) -> bool:
    """Whether every word of the name stands somewhere on the page."""
    stood = set(
        subtypes.level(
            " ".join(
                str(part or "")
                for part in (
                    page.name,
                    page.instagram_name,
                    page.instagram_username,
                    page.instagram_biography,
                    page.business_name,
                )
            )
        ).split()
    )
    asked = subtypes.level(name).split()
    return bool(asked) and all(word in stood for word in asked)


def keep(
    db: Session,
    *,
    business: Business,
    page: PageAccount,
    guess: KindGuess,
    now: datetime | None = None,
) -> Guessed:
    """Write a guess down as a guess; flushes. Nothing somebody of the
    business said is overwritten."""
    now = now or utcnow()
    view = known(db, business)
    direction_key = subtype_name = ""
    if view.type_state == TypeState.UNSET and guess.direction:
        direction = next(
            (row for row in offered_directions(db) if row.key == guess.direction),
            None,
        )
        if direction is not None:
            subtype = None
            if guess.subtype.strip():
                try:
                    subtype, _made = subtypes.ensure(
                        db, direction=direction, name=guess.subtype
                    )
                except BadSubtype:
                    subtype = None
            set_kind(
                db,
                business=business,
                direction=direction,
                subtype=subtype,
                state=TypeState.GUESSED,
                source=KnowledgeSource.PAGE,
                now=now,
            )
            direction_key = direction.key
            subtype_name = subtype.name if subtype is not None else ""
    renamed = False
    name = " ".join(guess.name.split())
    raw = str(page.name or page.instagram_name or "")
    untouched = business.name == raw
    if name and name != raw and untouched and _on_the_page(name, page):
        business.name = name[:255]
        business.updated_at = now
        db.flush()
        renamed = True
    proposed = False
    about = " ".join(guess.about.split())
    if about and not view.does:
        try:
            proposed = (
                knowledge.propose(
                    db,
                    business=business,
                    changes=[{"op": knowledge.SET_ABOUT, "text": about}],
                    source=KnowledgeSource.PAGE,
                    why="Sahifadagi ma'lumotdan",
                    now=now,
                )
                is not None
            )
        except BadKnowledgeChange:
            proposed = False
    return Guessed(
        direction=direction_key,
        subtype=subtype_name,
        renamed=renamed,
        proposed_about=proposed,
    )


def guess_kind(db: Session, *, business_id: str) -> Guessed | None:
    """Guess one business's kind from its page and keep it; the caller
    commits. Nothing for a business with no page, with a kind already said,
    or when the model cannot be reached."""
    business = db.get(Business, business_id)
    if business is None or business.page_id is None:
        return None
    page = db.get(PageAccount, business.page_id)
    if page is None or known(db, business).type_state != TypeState.UNSET:
        return None
    try:
        result = ask(db, page=page)
    except (LLMError, LLMUnavailable):
        logger.warning("kind_guess_failed", extra={"business": str(business.id)})
        return None
    if result is None:
        return None
    record_llm_result(
        db,
        owner=business.user,
        purpose=LLMPurpose.ONBOARDING,
        result=result,
        related_type=RELATED_TYPE,
        related_id=business.id,
    )
    done = keep(db, business=business, page=page, guess=result.value)
    logger.info(
        "kind_guessed",
        extra={
            "business": str(business.id),
            "direction": done.direction,
        },
    )
    return done


__all__ = ["Guessed", "ask", "guess_kind", "keep", "page_words"]
