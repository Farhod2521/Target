"""So'rovnomalar in the office, as JSON: the surveys, their languages, what
they found. Support, Finance and Owner. A refusal is the DomainError body; a
question's problems come under `questions.<index>`."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.api.deps import Db
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.common.timezone import localtime
from app.common.xlsx import workbook
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ADMIN_ROLES
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import person_out
from app.modules.backoffice.schemas import (
    CreatedOut,
    CustomerSurveysOut,
    MessageOut,
    SurveyDetailOut,
    SurveyResponseOut,
    SurveyResponsesOut,
    SurveyResultsOut,
    SurveyRosterOut,
    SurveyRowOut,
    SurveyTranslationOut,
)
from app.modules.surveys.constants import (
    ASK_AFTER_DAYS,
    ASK_AFTER_MAX_DAYS,
    INTRO_MAX,
    MAX_OPTIONS,
    MAX_QUESTIONS,
    MIN_OPTIONS,
    NAME_MAX,
    NUMBER_CEILING,
    NUMBER_FLOOR,
    OPTION_MAX,
    QUESTION_MAX,
    TITLE_MAX,
    QuestionKind,
    ResponseChannel,
)
from app.modules.surveys.drafts import (
    LanguageWording,
    QuestionDraft,
    QuestionWording,
    SurveyDraft,
)
from app.modules.surveys.languages import all_languages, targets
from app.modules.surveys.models import Survey, SurveyQuestion, SurveyResponse
from app.modules.surveys.selectors.office import (
    ResponseFilter,
    SurveyFull,
    answer_lines,
    audience_of,
    customer_responses,
    every_chosen,
    gist,
    language_tabs,
    phase,
    replied,
    response_by_id,
    response_page,
    survey_full,
    survey_people,
    survey_rows,
    translation_lost,
)
from app.modules.surveys.selectors.results import survey_results
from app.modules.surveys.selectors.sheet import survey_sheet
from app.modules.surveys.services import office as surveys
from core.surveys import rule_problem

router = APIRouter(prefix="/surveys")
customer_router = APIRouter(prefix="/customers/{customer_id}/surveys")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
RULE_PROBLEMS = {
    "later": "Shart faqat oldingi savolga bog'lanadi.",
    "kind": "Shart faqat tanlov savoliga bog'lanadi.",
    "options": "Shart uchun kamida bitta variantni belgilang.",
}


class QuestionIn(BaseModel):
    kind: QuestionKind
    text: str = ""
    options: list[str] = Field(default_factory=list)
    allows_many: bool = False
    min_value: int | None = None
    max_value: int | None = None
    is_required: bool = True
    show_if: int = Field(0, description="The earlier question's position; 0: always.")
    show_options: list[int] = Field(default_factory=list)


class SurveyIn(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    source_language: str
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    intro: str = Field("", max_length=INTRO_MAX)
    questions: list[QuestionIn]
    people: list[uuid.UUID] = Field(
        default_factory=list, description="Everyone ticked; nobody is everyone."
    )
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    ask_after_days: int = Field(ASK_AFTER_DAYS, ge=0, le=ASK_AFTER_MAX_DAYS)


class DuplicateIn(BaseModel):
    name: str = Field("", max_length=NAME_MAX, description="Empty: the original's.")
    keep_audience: bool = Field(
        False, description="Ask the same people; by default the copy asks everyone."
    )


class WordingQuestionIn(BaseModel):
    text: str = Field(max_length=QUESTION_MAX)
    options: list[str] = Field(default_factory=list)


class WordingIn(BaseModel):
    title: str = Field(max_length=TITLE_MAX)
    intro: str = Field("", max_length=INTRO_MAX)
    questions: list[WordingQuestionIn]


def _question_problems(item: QuestionIn) -> list[str]:
    problems: list[str] = []
    text = item.text.strip()
    if not text:
        problems.append("Savol matnini yozing.")
    elif len(text) > QUESTION_MAX:
        problems.append(f"Savol {QUESTION_MAX} belgidan oshmasin.")
    if item.kind == QuestionKind.CHOICE:
        options = [option.strip() for option in item.options if option.strip()]
        if len(options) < MIN_OPTIONS:
            problems.append(f"Kamida {MIN_OPTIONS} ta variant yozing.")
        elif len(options) > MAX_OPTIONS:
            problems.append(f"Ko'pi bilan {MAX_OPTIONS} ta variant.")
        if any(len(option) > OPTION_MAX for option in options):
            problems.append(f"Variant {OPTION_MAX} belgidan oshmasin.")
        if len({option.casefold() for option in options}) != len(options):
            problems.append("Variantlar takrorlanmasin.")
    if item.kind == QuestionKind.NUMBER:
        low, high = item.min_value, item.max_value
        if (
            low is None
            or high is None
            or low < NUMBER_FLOOR
            or high > NUMBER_CEILING
            or low >= high
        ):
            problems.append(
                "Eng kichik raqam eng kattasidan kam bo'lsin "
                f"({NUMBER_FLOOR} dan {NUMBER_CEILING} gacha)."
            )
    return problems


def _rule(item: QuestionIn, position: int, before: list[QuestionIn]) -> str:
    if not item.show_if:
        return ""
    above = before[item.show_if - 1] if 0 < item.show_if <= len(before) else None
    problem = rule_problem(
        position=position,
        parent=item.show_if,
        options=sorted(set(item.show_options)),
        parent_options=(
            len([option for option in above.options if option.strip()])
            if above is not None and above.kind == QuestionKind.CHOICE
            else -1
        ),
    )
    return RULE_PROBLEMS.get(problem, "") if problem else ""


def _draft(db: Db, body: SurveyIn, *, now: datetime) -> SurveyDraft:
    problems: dict[str, str] = {}
    if body.source_language not in all_languages():
        problems["source_language"] = "Tilni tanlang."
    if not body.name.strip():
        problems["name"] = "Ichki nomni yozing."
    if not body.title.strip():
        problems["title"] = "Sarlavhani yozing."
    if not body.questions:
        problems["questions"] = "Kamida bitta savol qo'shing."
    elif len(body.questions) > MAX_QUESTIONS:
        problems["questions"] = f"Ko'pi bilan {MAX_QUESTIONS} ta savol."
    if body.starts_at and body.ends_at and body.ends_at <= body.starts_at:
        problems["ends_at"] = "Tugash sanasi boshlanishidan keyin bo'lsin."
    questions = body.questions[:MAX_QUESTIONS]
    for index, item in enumerate(questions):
        found = _question_problems(item)
        rule = _rule(item, index + 1, questions[:index])
        if rule:
            found.append(rule)
        if found:
            problems[f"questions.{index}"] = " ".join(found)
    if problems:
        raise InputRefused(problems)
    chosen = set(body.people)
    roster = survey_people(db, now=now, chosen=chosen)
    return SurveyDraft(
        name=body.name,
        source_language=body.source_language,
        title=body.title,
        intro=body.intro,
        questions=tuple(
            QuestionDraft(
                kind=item.kind,
                text=item.text,
                options=(
                    tuple(option for option in item.options if option.strip())
                    if item.kind == QuestionKind.CHOICE
                    else ()
                ),
                allows_many=item.kind == QuestionKind.CHOICE and item.allows_many,
                min_value=item.min_value if item.kind == QuestionKind.NUMBER else None,
                max_value=item.max_value if item.kind == QuestionKind.NUMBER else None,
                is_required=item.is_required,
                show_if=item.show_if,
                show_options=tuple(sorted(set(item.show_options))),
            )
            for item in questions
        ),
        audience=audience_of(picked=chosen, roster=roster),
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        ask_after_days=body.ask_after_days,
    )


def _full(db: Db, survey_id: uuid.UUID) -> SurveyFull:
    found = survey_full(db, survey_id=survey_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return found


def _row_times(survey: Survey, *, now: datetime) -> dict[str, Any]:
    return {
        "active": survey.is_active,
        "published_at": survey.published_at,
        "starts_at": survey.starts_at,
        "ends_at": survey.ends_at,
        "ask_after_days": survey.ask_after_days,
        "phase": phase(survey, now=now),
        "state": survey.state,
        "created_at": survey.created_at,
    }


def _question_out(row: SurveyQuestion, lang: str) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "position": row.position,
        "kind": row.kind,
        "text": row.text.get(lang, ""),
        "options": [option.get(lang, "") for option in row.options],
        "allows_many": row.allows_many,
        "min_value": row.min_value,
        "max_value": row.max_value,
        "is_required": row.is_required,
        "show_if": row.show_if or 0,
        "show_options": list(row.show_options or []),
    }


def _response_row(row: SurveyResponse, done: set[uuid.UUID]) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "customer": person_out(row.owner),
        "survey": {"id": str(row.survey_id), "name": row.survey.name},
        "channel": row.channel,
        "language": row.language,
        "gist": gist(row),
        "replied": row.id in done,
        "at": row.created_at,
    }


@router.get("", responses={200: {"model": list[SurveyRowOut]}})
def surveys_list(db: Db, user: Admin) -> list[dict[str, Any]]:
    """Every survey, newest first."""
    now = utcnow()
    return [
        {
            **_row_times(row.survey, now=now),
            "id": str(row.survey.id),
            "name": row.survey.name,
            "audience": row.survey.audience,
            "plans": list(row.plans),
            "people": row.people,
            "questions": row.questions,
            "answers": row.answers,
        }
        for row in survey_rows(db)
    ]


@router.post("", responses={200: {"model": CreatedOut}})
def create(body: SurveyIn, db: Db, actor: Admin) -> dict[str, Any]:
    """A new survey, sent to be translated."""
    survey = surveys.create_survey(
        db, draft=_draft(db, body, now=utcnow()), actor=actor
    )
    db.commit()
    return {"message": "So'rovnoma saqlandi.", "id": str(survey.id)}


@router.get("/roster", responses={200: {"model": SurveyRosterOut}})
def roster(db: Db, user: Admin) -> dict[str, Any]:
    """Everyone a survey can be sent to by name, and the plans they are on."""
    persons = survey_people(db, now=utcnow(), chosen=every_chosen(db))
    counted: dict[str, dict[str, Any]] = {}
    for person in persons:
        if person["plan_id"]:
            line = counted.setdefault(
                person["plan_id"],
                {"id": person["plan_id"], "name": person["plan"], "total": 0},
            )
            line["total"] += 1
    return {"persons": persons, "plans": list(counted.values())}


@router.get("/responses", responses={200: {"model": SurveyResponsesOut}})
def responses(
    db: Db,
    user: Admin,
    survey: uuid.UUID | None = Query(None),
    plan: uuid.UUID | None = Query(None, description="Live on this plan today."),
    channel: ResponseChannel | None = Query(None),
    language: str = Query(""),
    since: date | None = Query(None),
    until: date | None = Query(None),
    unreplied: bool = Query(False, description="Nobody wrote to them since."),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The answers asked for, newest first, 50 at a time."""
    page = response_page(
        db,
        found=ResponseFilter(
            survey_id=survey,
            plan_id=plan,
            channel=str(channel) if channel else "",
            language=language,
            since=since,
            until=until,
            unreplied=unreplied,
        ),
        offset=offset,
    )
    done = replied(db, responses=page.rows)
    return {
        "rows": [_response_row(row, done) for row in page.rows],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
    }


@router.get("/responses/{response_id}", responses={200: {"model": SurveyResponseOut}})
def response(response_id: uuid.UUID, db: Db, user: Admin) -> dict[str, Any]:
    """One answer in full."""
    row = response_by_id(db, response_id=response_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    done = replied(db, responses=[row])
    return {
        **_response_row(row, done),
        "lines": answer_lines(db, response=row),
    }


@router.get("/{survey_id}", responses={200: {"model": SurveyDetailOut}})
def survey_detail(survey_id: uuid.UUID, db: Db, user: Admin) -> dict[str, Any]:
    """One survey in the language it is written in, with a tab per language."""
    full = _full(db, survey_id)
    survey = full.survey
    now = utcnow()
    lang = survey.source_language
    return {
        **_row_times(survey, now=now),
        "id": str(survey.id),
        "name": survey.name,
        "source_language": lang,
        "title": survey.title.get(lang, ""),
        "intro": survey.intro.get(lang, ""),
        "questions": [_question_out(row, lang) for row in full.questions],
        "people": [str(pk) for pk in full.people],
        "plans": [str(pk) for pk in full.plans],
        "answers": full.answers,
        "lost": translation_lost(survey, now=now),
        "tabs": language_tabs(survey, full.questions),
    }


@router.put("/{survey_id}", responses={200: {"model": MessageOut}})
def update(
    survey_id: uuid.UUID, body: SurveyIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Save it. Words a customer reads are translated again only if they changed."""
    _full(db, survey_id)
    surveys.update_survey(
        db, survey_id=survey_id, draft=_draft(db, body, now=utcnow()), actor=actor
    )
    db.commit()
    return {"message": "So'rovnoma saqlandi."}


@router.get(
    "/{survey_id}/languages/{language}",
    responses={200: {"model": SurveyTranslationOut}},
)
def translation(
    survey_id: uuid.UUID, language: str, db: Db, user: Admin
) -> dict[str, Any]:
    """One translated language beside the source words."""
    full = _full(db, survey_id)
    survey = full.survey
    if language not in targets(survey.source_language):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    lang = survey.source_language
    return {
        "language": language,
        "source": {
            "title": survey.title.get(lang, ""),
            "intro": survey.intro.get(lang, ""),
            "questions": [_question_out(row, lang) for row in full.questions],
        },
        "wording": {
            "title": survey.title.get(language, ""),
            "intro": survey.intro.get(language, ""),
            "questions": [
                {
                    "position": row.position,
                    "text": row.text.get(language, ""),
                    "options": [option.get(language, "") for option in row.options],
                }
                for row in full.questions
            ],
        },
    }


@router.put("/{survey_id}/languages/{language}", responses={200: {"model": MessageOut}})
def save_translation(
    survey_id: uuid.UUID, language: str, body: WordingIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Correct one language's words."""
    _full(db, survey_id)
    surveys.save_translation(
        db,
        survey_id=survey_id,
        language=language,
        wording=LanguageWording(
            title=body.title,
            intro=body.intro,
            questions=tuple(
                QuestionWording(text=item.text, options=tuple(item.options))
                for item in body.questions
            ),
        ),
        actor=actor,
    )
    db.commit()
    return {"message": "Tarjima saqlandi."}


def _act(db: Db, survey_id: uuid.UUID, message: str, action: Any) -> dict[str, Any]:
    _full(db, survey_id)
    action()
    db.commit()
    return {"message": message}


@router.post("/{survey_id}/publish", responses={200: {"model": MessageOut}})
def publish(survey_id: uuid.UUID, db: Db, actor: Admin) -> dict[str, Any]:
    """Start asking it; other live surveys stay live."""
    return _act(
        db,
        survey_id,
        "So'rovnoma e'lon qilindi.",
        lambda: surveys.publish_survey(
            db, survey_id=survey_id, actor=actor, now=utcnow()
        ),
    )


@router.post("/{survey_id}/stop", responses={200: {"model": MessageOut}})
def stop(survey_id: uuid.UUID, db: Db, actor: Admin) -> dict[str, Any]:
    """Nobody else is asked; the answers stay."""
    return _act(
        db,
        survey_id,
        "So'rovnoma yopildi.",
        lambda: surveys.stop_survey(db, survey_id=survey_id, actor=actor),
    )


@router.post("/{survey_id}/retranslate", responses={200: {"model": MessageOut}})
def retranslate(survey_id: uuid.UUID, db: Db, actor: Admin) -> dict[str, Any]:
    """Ask the AI again."""
    return _act(
        db,
        survey_id,
        "AI qaytadan tarjima qilmoqda.",
        lambda: surveys.retry_translation(
            db, survey_id=survey_id, actor=actor, now=utcnow()
        ),
    )


@router.post("/{survey_id}/delete", responses={200: {"model": MessageOut}})
def delete(survey_id: uuid.UUID, db: Db, actor: Admin) -> dict[str, Any]:
    """Remove a survey nobody is asked or has answered."""
    return _act(
        db,
        survey_id,
        "So'rovnoma o'chirildi.",
        lambda: surveys.delete_survey(db, survey_id=survey_id, actor=actor),
    )


@router.post("/{survey_id}/duplicate", responses={200: {"model": CreatedOut}})
def duplicate(
    survey_id: uuid.UUID, body: DuplicateIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """A closed copy with every language, to change and send to others."""
    _full(db, survey_id)
    copy = surveys.duplicate_survey(
        db,
        survey_id=survey_id,
        actor=actor,
        name=body.name,
        keep_audience=body.keep_audience,
    )
    db.commit()
    return {"message": "Nusxa yaratildi.", "id": str(copy.id)}


@router.get("/{survey_id}/results", responses={200: {"model": SurveyResultsOut}})
def results(survey_id: uuid.UUID, db: Db, user: Admin) -> dict[str, Any]:
    """Its funnel, each question's answers and the low scores."""
    return survey_results(db, full=_full(db, survey_id), now=utcnow())


@router.get("/{survey_id}/excel", response_class=Response)
def excel(survey_id: uuid.UUID, db: Db, user: Admin) -> Response:
    """A customer per row, a question per column."""
    survey = _full(db, survey_id).survey
    sheet = survey_sheet(db, survey=survey)
    content = workbook(sheet=survey.name, columns=sheet.columns, rows=sheet.rows)
    name = f"sorovnoma-{localtime():%Y-%m-%d}.xlsx"
    return Response(
        content,
        media_type=XLSX_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@customer_router.get("", responses={200: {"model": CustomerSurveysOut}})
def customer_surveys(customer_id: uuid.UUID, db: Db, user: Admin) -> dict[str, Any]:
    """What this customer answered, newest first, for their card."""
    rows = customer_responses(db, owner_id=customer_id)
    done = replied(db, responses=rows)
    return {
        "rows": [
            {
                "id": str(row.id),
                "survey": row.survey.name,
                "channel": row.channel,
                "gist": gist(row),
                "replied": row.id in done,
                "at": row.created_at,
            }
            for row in rows
        ]
    }
