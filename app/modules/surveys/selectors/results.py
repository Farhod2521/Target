"""What a survey found: its funnel, each question's answers, and the low scores.

A half-finished answer counts in each question it answered, and as started,
not answered, in the funnel.

Read in Python over one survey's answers: a survey's answers are hundreds, not
thousands, and an answer is a JSON list.
"""

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.common.timezone import localtime
from app.modules.surveys.constants import (
    LOW_SCORE_SHARE,
    RESULT_LOW_SCORES,
    RESULT_TEXTS,
    QuestionKind,
)
from app.modules.surveys.models import SurveyQuestion, SurveyResponse, SurveySighting
from app.modules.surveys.selectors.office import (
    SurveyFull,
    office_language,
    reached,
    replied,
)
from core.surveys import Rule, asked_positions


@dataclass(frozen=True, slots=True)
class Funnel:
    """`meant`: live customers it is for, and whoever answered before their
    plan ended. `seen` holds everyone who answered, since a survey sent before
    sightings were kept has none for them."""

    meant: int
    seen: int
    later: int
    answered: int
    partial: int = 0

    @property
    def rate_percent(self) -> float:
        return round(self.answered * 100 / self.meant, 1) if self.meant else 0.0


def _percent(part: int, whole: int) -> float:
    return round(part * 100 / whole, 1) if whole else 0.0


def _is_low(number: int, row: SurveyQuestion) -> bool:
    low, high = row.min_value or 0, row.max_value or 0
    return number <= low + (high - low) * LOW_SCORE_SHARE


def _was_asked(
    row: SurveyQuestion, picks: dict[int, set[int]], rules: list[Rule]
) -> bool:
    return row.position in set(asked_positions(rules, picks))


def _picks(
    questions: list[SurveyQuestion], said: dict[str, dict[str, Any]]
) -> dict[int, set[int]]:
    return {
        row.position: {
            pick
            for pick in said.get(str(row.id), {}).get("choices") or []
            if isinstance(pick, int)
        }
        for row in questions
        if row.kind == QuestionKind.CHOICE
    }


def _question_result(
    row: SurveyQuestion,
    *,
    lang: str,
    answers: list[tuple[SurveyResponse, dict[str, Any]]],
    asked: int,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "position": row.position,
        "kind": row.kind,
        "text": row.text.get(lang, ""),
        "asked": asked,
        "answered": len(answers),
        "options": [],
        "numbers": [],
        "average": None,
        "min_value": row.min_value,
        "max_value": row.max_value,
        "texts": [],
    }
    if row.kind == QuestionKind.CHOICE:
        picked = Counter(
            pick
            for _, item in answers
            for pick in item.get("choices") or []
            if isinstance(pick, int)
        )
        base["options"] = [
            {
                "label": option.get(lang, ""),
                "count": picked.get(index, 0),
                "percent": _percent(picked.get(index, 0), len(answers)),
            }
            for index, option in enumerate(row.options)
        ]
    elif row.kind == QuestionKind.NUMBER:
        numbers = [
            item["number"] for _, item in answers if isinstance(item.get("number"), int)
        ]
        counted = Counter(numbers)
        base["numbers"] = [
            {
                "value": value,
                "count": counted.get(value, 0),
                "percent": _percent(counted.get(value, 0), len(numbers)),
                "low": _is_low(value, row),
            }
            for value in range(row.min_value or 0, (row.max_value or 0) + 1)
        ]
        base["average"] = round(sum(numbers) / len(numbers), 1) if numbers else None
    else:
        base["texts"] = [
            {
                "response_id": str(response.id),
                "name": response.owner.full_name or response.owner.email,
                "text": str(item.get("text") or ""),
            }
            for response, item in answers[:RESULT_TEXTS]
        ]
    return base


def survey_results(db: Session, *, full: SurveyFull, now: datetime) -> dict[str, Any]:
    survey = full.survey
    lang = office_language(survey)
    questions = list(full.questions)
    responses = list(
        db.scalars(
            select(SurveyResponse)
            .options(joinedload(SurveyResponse.owner))
            .where(SurveyResponse.survey_id == survey.id)
            .order_by(SurveyResponse.created_at.desc())
        )
    )
    answered = {row.owner_id for row in responses if row.completed_at is not None}
    started = {row.owner_id for row in responses}
    sightings = list(
        db.scalars(select(SurveySighting).where(SurveySighting.survey_id == survey.id))
    )
    seen: set[uuid.UUID] = {row.owner_id for row in sightings} | started
    funnel = Funnel(
        meant=len(reached(db, full=full, now=now) | started),
        seen=len(seen),
        later=sum(1 for row in sightings if row.later_count),
        answered=len(answered),
        partial=len(started - answered),
    )
    rules = [
        Rule(row.position, row.show_if or 0, tuple(row.show_options or ()))
        for row in questions
    ]
    per_question: dict[uuid.UUID, list[tuple[SurveyResponse, dict[str, Any]]]] = {}
    asked_count: Counter[uuid.UUID] = Counter()
    low: list[dict[str, Any]] = []
    done = replied(db, responses=responses)
    days: Counter[str] = Counter()
    channels: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    for response in responses:
        said = {str(item.get("question")): item for item in response.answers}
        picks = _picks(questions, said)
        days[
            localtime(response.completed_at or response.created_at).date().isoformat()
        ] += 1
        channels[response.channel] += 1
        languages[response.language] += 1
        for row in questions:
            if _was_asked(row, picks, rules):
                asked_count[row.id] += 1
            item = said.get(str(row.id))
            if item is None or not _has_answer(row, item):
                continue
            per_question.setdefault(row.id, []).append((response, item))
            number = item.get("number")
            if (
                row.kind == QuestionKind.NUMBER
                and isinstance(number, int)
                and _is_low(number, row)
            ):
                low.append(
                    {
                        "response_id": str(response.id),
                        "customer_id": str(response.owner_id),
                        "name": response.owner.full_name or response.owner.email,
                        "question": row.text.get(lang, ""),
                        "number": number,
                        "max_value": row.max_value,
                        "replied": response.id in done,
                        "at": response.created_at,
                    }
                )
    low.sort(key=lambda line: (line["replied"], line["number"]))
    return {
        "funnel": {
            "meant": funnel.meant,
            "seen": funnel.seen,
            "later": funnel.later,
            "answered": funnel.answered,
            "partial": funnel.partial,
            "rate_percent": funnel.rate_percent,
        },
        "days": [{"day": day, "count": days[day]} for day in sorted(days)],
        "channels": dict(channels),
        "languages": dict(languages),
        "questions": [
            _question_result(
                row,
                lang=lang,
                answers=per_question.get(row.id, []),
                asked=asked_count.get(row.id, 0),
            )
            for row in questions
        ],
        "low_scores": low[:RESULT_LOW_SCORES],
        "low_total": len(low),
    }


def _has_answer(row: SurveyQuestion, item: dict[str, Any]) -> bool:
    if row.kind == QuestionKind.TEXT:
        return bool(str(item.get("text") or "").strip())
    if row.kind == QuestionKind.CHOICE:
        return bool(item.get("choices"))
    return item.get("number") is not None
