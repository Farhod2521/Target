"""The product's known problems and their steps, searched for the assistant.

Three shelves, read in this order: the office's own articles
(``help_articles``, written in three languages), the video lessons, and the
fixes the code already carries for Meta's errors and refusals (``GUIDES``).
A search is plain word overlap - there are tens of articles, not thousands -
and returns the steps themselves, so the model copies them instead of
writing its own.
"""

import re
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assistant.constants import (
    HELP_LANGUAGES,
    HELP_RESULTS,
    HELP_STEPS_CHARS,
)
from app.modules.assistant.models import HelpArticle

WORD: Final = re.compile(r"[\w']+", re.UNICODE)
APOSTROPHES: Final = str.maketrans(dict.fromkeys("‘’ʻʼ`", "'"))
MIN_WORD: Final = 3
# A hit in the problem's own name or its keywords is worth more than one
# somewhere in the steps.
TITLE_WEIGHT: Final = 3
NOTHING: Final = "nothing found - there is no written fix for this."


@dataclass(frozen=True, slots=True)
class Found:
    """One thing a search returned, ready to be shown to the model."""

    score: int
    shelf: str
    problem: str
    steps: tuple[str, ...]


def help_search(db: Session, *, query: str, language: str) -> str:
    """The best few matches, each with its steps."""
    wanted = _words(query)
    if not wanted:
        return NOTHING
    found = sorted(
        (
            item
            for item in (
                *_articles(db, wanted=wanted, language=language),
                *_lessons(db, wanted=wanted),
                *_guides(wanted=wanted),
            )
            if item.score > 0
        ),
        key=lambda item: -item.score,
    )[:HELP_RESULTS]
    if not found:
        return NOTHING
    blocks: list[str] = []
    for item in found:
        lines = [f"## {item.problem} ({item.shelf})"]
        lines += [f"{index}. {step}" for index, step in enumerate(item.steps, start=1)]
        blocks.append("\n".join(lines)[:HELP_STEPS_CHARS])
    return "\n\n".join(blocks)


def _words(text: str) -> frozenset[str]:
    folded = text.casefold().translate(APOSTROPHES)
    return frozenset(word for word in WORD.findall(folded) if len(word) >= MIN_WORD)


def _score(wanted: frozenset[str], *, title: str, body: str) -> int:
    """How many of the asked words are here - by their first letters, so
    "to'lovim" finds "to'lov" and "ulanmayapti" finds "ulanish"."""
    heads = _words(title)
    rest = _words(body)
    score = 0
    for word in wanted:
        stem = word[: max(MIN_WORD + 1, len(word) - 3)]
        if any(
            other.startswith(stem) or word.startswith(other[: len(stem)])
            for other in heads
        ):
            score += TITLE_WEIGHT
        elif any(other.startswith(stem) for other in rest):
            score += 1
    return score


def _in(language: str) -> str:
    return language if language in HELP_LANGUAGES else HELP_LANGUAGES[0]


def _articles(db: Session, *, wanted: frozenset[str], language: str) -> list[Found]:
    code = _in(language)
    rows = db.scalars(
        select(HelpArticle)
        .where(HelpArticle.is_published.is_(True))
        .order_by(HelpArticle.position, HelpArticle.created_at)
    )
    found: list[Found] = []
    for row in rows:
        problem = getattr(row, f"problem_{code}") or row.problem_uz
        steps = getattr(row, f"steps_{code}") or row.steps_uz
        every_title = " ".join(
            (row.problem_uz, row.problem_ru, row.problem_en, row.keywords)
        )
        every_body = " ".join((row.steps_uz, row.steps_ru, row.steps_en))
        found.append(
            Found(
                score=_score(wanted, title=every_title, body=every_body),
                shelf="the team's article",
                problem=problem,
                steps=tuple(
                    line.strip() for line in steps.splitlines() if line.strip()
                ),
            )
        )
    return found


def _lessons(db: Session, *, wanted: frozenset[str]) -> list[Found]:
    from app.modules.tutorials.models import Tutorial

    rows = db.scalars(select(Tutorial).where(Tutorial.is_active.is_(True)))
    return [
        Found(
            score=_score(wanted, title=row.title, body=row.description),
            shelf="a video lesson in the cabinet's Darsliklar",
            problem=row.title,
            steps=tuple(
                line.strip()
                for line in (row.description or "").splitlines()
                if line.strip()
            )
            or ("Darsliklar bo'limida shu nomdagi videoni oching.",),
        )
        for row in rows
    ]


def _guides(*, wanted: frozenset[str]) -> list[Found]:
    from app.modules.ads.selectors import failures, rejections

    found: list[Found] = []
    for shelf, guides in (
        ("the product's fix for a Meta error", failures.GUIDES),
        ("the product's fix for a refused advert", rejections.GUIDES),
    ):
        seen: set[str] = set()
        for code, (sentence, steps) in guides.items():
            if sentence in seen:
                continue
            seen.add(sentence)
            found.append(
                Found(
                    score=_score(
                        wanted, title=f"{sentence} {code}", body=" ".join(steps)
                    ),
                    shelf=shelf,
                    problem=sentence,
                    steps=tuple(str(step) for step in steps),
                )
            )
    return found


__all__ = ["NOTHING", "Found", "help_search"]
