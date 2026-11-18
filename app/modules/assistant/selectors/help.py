"""The product's known problems and their steps, searched for the assistant.

Three shelves, read in this order: the office's own articles
(``help_articles``, written in three languages), the video lessons, and the
ready answers the code already carries for Meta's errors: a refused
creation (``contract/launch/failures``), an advert Meta will not run
(``delivery_issues``, ``rejections``) and a change that did not go through
(``failures``).

A search is word overlap - there are a hundred answers, not thousands - with
two rules that keep a wrong answer out. A code (ours, such as
``page_terms``, or Meta's, such as ``1885316``) finds its own answer and
nothing else. And a word nearly every answer has ("reklama", "meta") finds
nothing by itself: an answer is returned only when a word of its own was
asked for. The steps themselves are returned, so the model copies them
instead of writing its own.
"""

import re
from dataclasses import dataclass, replace
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
# A word found in the names of more than this share of the answers tells
# them apart from nothing.
COMMON_SHARE: Final = 0.2
# Words of a question, not of a problem.
STOP: Final = frozenset(
    {
        "qanday",
        "qanaqa",
        "nima",
        "nega",
        "nimaga",
        "qachon",
        "qayerda",
        "qilish",
        "qilaman",
        "qilay",
        "kerak",
        "uchun",
        "bilan",
        "emas",
        "hech",
        "hozir",
        "menga",
        "mening",
        "bor",
        "yo'q",
        "ham",
        "yoki",
        "как",
        "что",
        "почему",
        "когда",
        "где",
        "надо",
        "нужно",
        "для",
        "или",
        "это",
        "меня",
        "мой",
        "how",
        "what",
        "why",
        "when",
        "where",
        "the",
        "and",
        "for",
        "with",
        "not",
    }
)
# An exact code is the answer asked for.
CODE_WEIGHT: Final = 100
NOTHING: Final = "nothing found - there is no written fix for this."


@dataclass(frozen=True, slots=True)
class Found:
    """One thing a search returned, ready to be shown to the model."""

    shelf: str
    problem: str
    steps: tuple[str, ...]
    # Other words for it: what people call it, and its codes.
    keywords: str = ""
    body: str = ""
    codes: frozenset[str] = frozenset()
    score: int = 0
    # A video lesson's id: the page draws a card that opens it.
    lesson_id: str = ""


def help_search(db: Session, *, query: str, language: str) -> str:
    """The best few matches, each with its steps."""
    return help_text(help_found(db, query=query, language=language))


def help_found(db: Session, *, query: str, language: str) -> list[Found]:
    """The best few matches themselves."""
    wanted = _asked(query)
    if not wanted:
        return []
    return ranked(
        [
            *_articles(db, language=language),
            *_lessons(db),
            *_launches(),
            *_troubles(),
            *_guides(),
        ],
        wanted=wanted,
    )[:HELP_RESULTS]


def help_text(found: list[Found]) -> str:
    """What was found as the model reads it."""
    if not found:
        return NOTHING
    blocks: list[str] = []
    for item in found:
        lines = [f"## {item.problem} ({item.shelf})"]
        lines += [f"{index}. {step}" for index, step in enumerate(item.steps, start=1)]
        blocks.append("\n".join(lines)[:HELP_STEPS_CHARS])
    return "\n\n".join(blocks)


def ranked(items: list[Found], *, wanted: frozenset[str]) -> list[Found]:
    """The answers these words ask for, best first.

    A code asked for returns its answers only. Otherwise each answer is
    scored by the asked words found in it, leaving out the words that are in
    most answers' names; one with no word of its own name asked for is not
    an answer to this question.
    """
    by_code = [item for item in items if item.codes & wanted]
    if by_code:
        return [replace(item, score=CODE_WEIGHT) for item in by_code]
    names = [_words(f"{item.problem} {item.keywords}") for item in items]
    rare = frozenset(
        word
        for word in wanted
        if sum(_has(word, name) for name in names) <= len(items) * COMMON_SHARE
    )
    found: list[Found] = []
    for item, name in zip(items, names, strict=True):
        rest = _words(item.body or " ".join(item.steps))
        named = sum(TITLE_WEIGHT for word in rare if _has(word, name))
        if not named:
            continue
        told = sum(1 for word in wanted if not _has(word, name) and _has(word, rest))
        found.append(replace(item, score=named + told))
    return sorted(found, key=lambda item: -item.score)


def _words(text: str) -> frozenset[str]:
    folded = text.casefold().translate(APOSTROPHES)
    return frozenset(word for word in WORD.findall(folded) if len(word) >= MIN_WORD)


def _asked(text: str) -> frozenset[str]:
    """The words of a question that could name a problem."""
    return _words(text) - STOP


def _has(word: str, others: frozenset[str]) -> bool:
    """Whether a word is among these - by its first letters, so "to'lovim"
    finds "to'lov" and "ulanmayapti" finds "ulanish"."""
    stem = word[: max(MIN_WORD + 1, len(word) - 3)]
    return any(
        other.startswith(stem) or word.startswith(other[: len(stem)])
        for other in others
    )


def _in(language: str) -> str:
    return language if language in HELP_LANGUAGES else HELP_LANGUAGES[0]


def _articles(db: Session, *, language: str) -> list[Found]:
    code = _in(language)
    rows = db.scalars(
        select(HelpArticle)
        .where(HelpArticle.is_published.is_(True))
        .order_by(HelpArticle.position, HelpArticle.created_at)
    )
    found: list[Found] = []
    for row in rows:
        # The reader's language, else whichever the office has written.
        problem = next(
            (
                words
                for words in (
                    getattr(row, f"problem_{code}"),
                    row.problem_uz,
                    row.problem_ru,
                    row.problem_en,
                )
                if words
            ),
            "",
        )
        steps = next(
            (
                words
                for words in (
                    getattr(row, f"steps_{code}"),
                    row.steps_uz,
                    row.steps_ru,
                    row.steps_en,
                )
                if words
            ),
            "",
        )
        if not (problem and steps):
            continue
        found.append(
            Found(
                shelf="the team's article",
                problem=problem,
                steps=tuple(
                    line.strip() for line in steps.splitlines() if line.strip()
                ),
                keywords=" ".join(
                    (row.problem_uz, row.problem_ru, row.problem_en, row.keywords)
                ),
                body=" ".join((row.steps_uz, row.steps_ru, row.steps_en)),
                codes=_words(row.code),
            )
        )
    return found


def _lessons(db: Session) -> list[Found]:
    from app.modules.tutorials.models import Tutorial

    rows = db.scalars(select(Tutorial).where(Tutorial.is_active.is_(True)))
    return [
        Found(
            shelf="a video lesson in the cabinet's Darsliklar",
            problem=row.title,
            steps=tuple(
                line.strip()
                for line in (row.description or "").splitlines()
                if line.strip()
            )
            or ("Darsliklar bo'limida shu nomdagi videoni oching.",),
            lesson_id=str(row.id),
        )
        for row in rows
    ]


# What people call each kind of trouble, in the three languages: the answers
# themselves are written in Uzbek.
REFUSAL_WORDS: Final = (
    "rad etildi rad etdi rad qilindi tasdiqlanmadi moderatsiya "
    "отклонена отклонили не одобрена модерация rejected disapproved refused"
)
CHANGE_WORDS: Final = (
    "o'zgarmadi saqlanmadi to'xtamadi yoqilmadi o'chmadi tugma ishlamadi "
    "не сохранилось не изменилось не включается change failed"
)
ANSWER_WORDS: Final[dict[str, str]] = {
    "page_terms": "lid shartlari shartlar qabul terms условия лид-формы",
    "payment": "to'lov karta qarz billing оплата карта долг payment card",
    "payment_missing": "to'lov karta оплата карта payment card",
    "account_blocked": "to'lov qarz bloklangan cheklangan долг ограничен",
    "token": "ulanish uzilgan qayta ulash подключение переподключить reconnect",
    "reconnect": "ulanish uzilgan qayta ulash подключение переподключить",
    "connection": "ulanish uzilgan qayta ulash подключение переподключить",
    "account_disabled": "akkaunt o'chirilgan bloklangan disabled отключен заблокирован",
    "page_restricted": "sahifa cheklangan bloklangan страница ограничена restricted",
    "budget_low": "byudjet kam minimum бюджет минимальный budget",
    "text_phone": "telefon raqam matnda номер телефона в тексте phone",
    "policy": "qoida kafolat va'da правила политика policy",
    "media_too_large": "hajmi katta fayl og'ir размер большой файл size",
    "media_unsupported": "format mos emas формат не подходит format",
    "video_not_ready": "video tayyor emas yuklanmoqda видео обрабатывается",
    "site_unreachable": "sayt ochilmayapti ishlamayapti сайт не открывается",
    "location_invalid": "hudud joy shahar регион город location",
    "interest_retired": "qiziqish interes интерес interest",
    "instagram_profile": "instagram profil инстаграм",
}


def _launches() -> list[Found]:
    """A creation Meta refused: one answer per code of ours."""
    from app.modules.ads.contract.launch.failures import guides
    from app.modules.ads.contract.launch.words import FAILURES

    names: dict[str, set[str]] = {}
    for alias, code in FAILURES.items():
        names.setdefault(code, {code}).add(alias)
    return [
        Found(
            shelf="the product's fix for an advert that was not created",
            problem=guide.title,
            steps=guide.steps,
            keywords=ANSWER_WORDS.get(guide.code, ""),
            body=guide.cause,
            codes=frozenset(names.get(guide.code, {guide.code})),
        )
        for guide in guides()
    ]


def _troubles() -> list[Found]:
    """An advert Meta will not run, by Meta's own code: one answer may
    stand for several codes."""
    from app.modules.ads.selectors.delivery_issues import TROUBLES, Trouble

    codes: dict[int, set[str]] = {}
    kept: dict[int, Trouble] = {}
    for code, trouble in TROUBLES.items():
        codes.setdefault(id(trouble), set()).add(code)
        kept[id(trouble)] = trouble
    return [
        Found(
            shelf="the product's fix for an advert Meta will not run",
            problem=trouble.title,
            steps=tuple(trouble.steps),
            body=trouble.cause,
            codes=frozenset(codes[key]),
        )
        for key, trouble in kept.items()
    ]


def _guides() -> list[Found]:
    """A change that did not go through, and a review's refusal."""
    from app.modules.ads.selectors import failures, rejections

    found: list[Found] = []
    for shelf, guides, words in (
        (
            "the product's fix for a change Meta did not take",
            failures.GUIDES,
            CHANGE_WORDS,
        ),
        ("the product's fix for a refused advert", rejections.GUIDES, REFUSAL_WORDS),
    ):
        by_sentence: dict[str, Found] = {}
        for code, (sentence, steps) in guides.items():
            earlier = by_sentence.get(sentence)
            by_sentence[sentence] = Found(
                shelf=shelf,
                problem=sentence,
                steps=tuple(
                    str(step).replace("Pastda Meta yozgan", "Meta yozgan")
                    for step in steps
                ),
                keywords=f"{words} {ANSWER_WORDS.get(code, '')}",
                codes=frozenset({code}) | (earlier.codes if earlier else frozenset()),
            )
        found += by_sentence.values()
    return found


__all__ = ["NOTHING", "Found", "help_found", "help_search", "help_text", "ranked"]
