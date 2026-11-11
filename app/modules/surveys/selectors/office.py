"""Surveys for the office: the list, one survey, who it reaches, the answers."""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, func, select, true
from sqlalchemy.orm import Session, joinedload

from app.common.timezone import localtime
from app.modules.accounts.models import User
from app.modules.backoffice.constants import PAGE_SIZE
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    SubscriptionStatus,
)
from app.modules.billing.models import Plan, Subscription
from app.modules.supportchat.models import SupportConversation
from app.modules.surveys.constants import (
    GIST_CHARS,
    OFFICE_LANGUAGE,
    TRANSLATION_STALE_MINUTES,
    QuestionKind,
    SurveyAudience,
    SurveyState,
)
from app.modules.surveys.drafts import AudienceDraft
from app.modules.surveys.languages import targets
from app.modules.surveys.models import (
    Survey,
    SurveyQuestion,
    SurveyResponse,
    surveys_people,
    surveys_plans,
)


@dataclass(frozen=True, slots=True)
class SurveyRow:
    survey: Survey
    plans: tuple[str, ...]
    people: int
    questions: int
    answers: int
    partial: int


@dataclass(frozen=True, slots=True)
class SurveyFull:
    survey: Survey
    questions: tuple[SurveyQuestion, ...]
    plans: tuple[uuid.UUID, ...]
    people: tuple[uuid.UUID, ...]
    answers: int
    partial: int = 0


@dataclass(frozen=True, slots=True)
class ResponseFilter:
    survey_id: uuid.UUID | None = None
    plan_id: uuid.UUID | None = None
    channel: str = ""
    language: str = ""
    since: date | None = None
    until: date | None = None
    unreplied: bool = False
    finished: bool | None = None


@dataclass(frozen=True, slots=True)
class ResponsePage:
    rows: tuple[SurveyResponse, ...]
    total: int
    offset: int

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.rows)

    @property
    def has_more(self) -> bool:
        return self.next_offset < self.total


def phase(survey: Survey, *, now: datetime) -> str:
    """Where a survey is in its life, its dates read at this moment."""
    if not survey.is_active:
        return "closed" if survey.published_at else "draft"
    if survey.ends_at is not None and survey.ends_at <= now:
        return "ended"
    if survey.starts_at is not None and survey.starts_at > now:
        return "scheduled"
    return "live"


def translation_lost(survey: Survey, *, now: datetime) -> bool:
    lost = now - timedelta(minutes=TRANSLATION_STALE_MINUTES)
    return survey.state == SurveyState.TRANSLATING and survey.updated_at <= lost


def _counted(db: Session, column: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(column, func.count()).where(column.in_(ids)).group_by(column)
    )
    return {key: int(total) for key, total in rows}


def _answer_counts(
    db: Session, ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    """Finished and half-finished answers, per survey."""
    finished: dict[uuid.UUID, int] = {}
    partial: dict[uuid.UUID, int] = {}
    for survey_id, done, total in db.execute(
        select(
            SurveyResponse.survey_id,
            SurveyResponse.completed_at.is_not(None),
            func.count(),
        )
        .where(SurveyResponse.survey_id.in_(ids))
        .group_by(SurveyResponse.survey_id, SurveyResponse.completed_at.is_not(None))
    ):
        (finished if done else partial)[survey_id] = int(total)
    return finished, partial


def survey_rows(db: Session) -> list[SurveyRow]:
    """Every survey not deleted, newest first."""
    surveys = list(
        db.scalars(
            select(Survey)
            .where(Survey.deleted_at.is_(None))
            .order_by(Survey.created_at.desc())
        )
    )
    ids = [row.id for row in surveys]
    if not ids:
        return []
    questions = _counted(db, SurveyQuestion.survey_id, ids)
    answers, partial = _answer_counts(db, ids)
    people = _counted(db, surveys_people.c.survey_id, ids)
    plans: dict[uuid.UUID, list[str]] = {}
    for survey_id, name in db.execute(
        select(surveys_plans.c.survey_id, Plan.name)
        .join(Plan, Plan.id == surveys_plans.c.plan_id)
        .where(surveys_plans.c.survey_id.in_(ids))
    ):
        plans.setdefault(survey_id, []).append(name)
    return [
        SurveyRow(
            survey=row,
            plans=tuple(plans.get(row.id, ())),
            people=people.get(row.id, 0),
            questions=questions.get(row.id, 0),
            answers=answers.get(row.id, 0),
            partial=partial.get(row.id, 0),
        )
        for row in surveys
    ]


def questions_of(db: Session, survey_id: uuid.UUID) -> list[SurveyQuestion]:
    return list(
        db.scalars(
            select(SurveyQuestion)
            .where(SurveyQuestion.survey_id == survey_id)
            .order_by(SurveyQuestion.position)
        )
    )


def survey_full(db: Session, *, survey_id: uuid.UUID) -> SurveyFull | None:
    survey = db.get(Survey, survey_id)
    if survey is None or survey.deleted_at is not None:
        return None
    plans = db.scalars(
        select(surveys_plans.c.plan_id).where(surveys_plans.c.survey_id == survey_id)
    )
    people = db.scalars(
        select(surveys_people.c.user_id).where(surveys_people.c.survey_id == survey_id)
    )
    answers, partial = _answer_counts(db, [survey_id])
    return SurveyFull(
        survey=survey,
        questions=tuple(questions_of(db, survey_id)),
        plans=tuple(plans),
        people=tuple(people),
        answers=answers.get(survey_id, 0),
        partial=partial.get(survey_id, 0),
    )


def filled(survey: Survey, questions: Collection[SurveyQuestion], code: str) -> bool:
    if not survey.title.get(code, "").strip():
        return False
    has_intro = bool(survey.intro.get(survey.source_language, ""))
    if has_intro and not survey.intro.get(code, "").strip():
        return False
    return all(
        row.text.get(code, "").strip()
        and all(option.get(code, "").strip() for option in row.options)
        for row in questions
    )


def language_tabs(
    survey: Survey, questions: Collection[SurveyQuestion]
) -> list[dict[str, Any]]:
    codes = [survey.source_language, *targets(survey.source_language)]
    return [
        {
            "code": code,
            "source": code == survey.source_language,
            "filled": filled(survey, questions, code),
        }
        for code in codes
    ]


def _live_customers(*, now: datetime) -> Select[Any]:
    return (
        select(Subscription)
        .join(User, Subscription.owner_id == User.id)
        .options(joinedload(Subscription.owner), joinedload(Subscription.plan))
        .where(
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > now,
            User.is_staff.is_(False),
        )
        .order_by(User.email)
    )


def _person(user: User, *, plan_id: str, plan: str, trial: bool) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
        "phone": user.phone,
        "plan_id": plan_id,
        "plan": plan,
        "trial": trial,
        "staff": bool(user.is_staff),
    }


def survey_people(
    db: Session, *, now: datetime, chosen: Collection[uuid.UUID]
) -> list[dict[str, Any]]:
    """The customers on a live plan, a trial included; the staff, to try a
    survey on themselves; and those already `chosen` whose plan has lapsed: a
    saved choice never drops out of sight."""
    people = [
        _person(
            row.owner,
            plan_id=str(row.plan_id),
            plan=row.plan.name,
            trial=row.status == SubscriptionStatus.TRIAL,
        )
        for row in db.scalars(_live_customers(now=now)).unique()
    ]
    staff = db.scalars(
        select(User)
        .where(User.is_staff.is_(True), User.is_active.is_(True))
        .order_by(User.email)
    )
    people += [_person(user, plan_id="", plan="", trial=False) for user in staff]
    seen = {person["id"] for person in people}
    missing = [pk for pk in chosen if str(pk) not in seen]
    gone = db.scalars(select(User).where(User.id.in_(missing))) if missing else ()
    return people + [_person(user, plan_id="", plan="", trial=False) for user in gone]


def every_chosen(db: Session) -> set[uuid.UUID]:
    return set(db.scalars(select(surveys_people.c.user_id)))


def audience_of(
    *, picked: Collection[uuid.UUID], roster: list[dict[str, Any]]
) -> AudienceDraft:
    """Who the ticked people are, as a survey keeps it. Nobody, or every
    customer on a live plan and no staff: everyone. Otherwise each plan whose
    every live customer is ticked is kept whole, and whoever else is ticked by
    name - staff always by name, since "everyone" never asks them."""
    chosen = {str(pk) for pk in picked}
    members: dict[str, set[str]] = {}
    staff: set[str] = set()
    for person in roster:
        if person["plan_id"]:
            members.setdefault(person["plan_id"], set()).add(person["id"])
        if person.get("staff"):
            staff.add(person["id"])
    live = set().union(*members.values()) if members else set()
    if not chosen or (live and live <= chosen and not chosen & staff):
        return AudienceDraft()
    whole = [plan for plan, ids in members.items() if ids <= chosen]
    covered = set().union(*(members[plan] for plan in whole)) if whole else set()
    people = sorted(chosen - covered)
    return AudienceDraft(
        kind=SurveyAudience.PEOPLE if people else SurveyAudience.PLANS,
        plans=tuple(uuid.UUID(plan) for plan in sorted(whole)),
        people=tuple(uuid.UUID(pk) for pk in people),
    )


def reached(db: Session, *, full: SurveyFull, now: datetime) -> set[uuid.UUID]:
    """The customers this survey is meant for at this moment."""
    survey = full.survey
    rows = db.scalars(_live_customers(now=now)).unique()
    if survey.audience == SurveyAudience.EVERYONE:
        return {row.owner_id for row in rows}
    plans, people = set(full.plans), set(full.people)
    return {row.owner_id for row in rows if row.plan_id in plans} | people


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=localtime().tzinfo)


def _filtered(found: ResponseFilter) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = [true()]
    if found.survey_id is not None:
        where.append(SurveyResponse.survey_id == found.survey_id)
    if found.channel:
        where.append(SurveyResponse.channel == found.channel)
    if found.language:
        where.append(SurveyResponse.language == found.language)
    if found.since is not None:
        where.append(SurveyResponse.created_at >= _day_start(found.since))
    if found.until is not None:
        where.append(
            SurveyResponse.created_at < _day_start(found.until + timedelta(days=1))
        )
    if found.plan_id is not None:
        where.append(
            exists().where(
                Subscription.owner_id == SurveyResponse.owner_id,
                Subscription.plan_id == found.plan_id,
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            )
        )
    if found.finished is not None:
        where.append(
            SurveyResponse.completed_at.is_not(None)
            if found.finished
            else SurveyResponse.completed_at.is_(None)
        )
    if found.unreplied:
        where.append(
            ~exists().where(
                SupportConversation.owner_id == SurveyResponse.owner_id,
                SupportConversation.last_office_at >= SurveyResponse.created_at,
            )
        )
    return where


def response_page(
    db: Session, *, found: ResponseFilter, offset: int = 0
) -> ResponsePage:
    """The answers asked for, newest first."""
    where = _filtered(found)
    total = db.scalar(select(func.count(SurveyResponse.id)).where(*where))
    rows = db.scalars(
        select(SurveyResponse)
        .options(joinedload(SurveyResponse.owner), joinedload(SurveyResponse.survey))
        .where(*where)
        .order_by(SurveyResponse.created_at.desc(), SurveyResponse.id)
        .offset(offset)
        .limit(PAGE_SIZE)
    )
    return ResponsePage(rows=tuple(rows), total=int(total or 0), offset=offset)


def customer_responses(db: Session, *, owner_id: uuid.UUID) -> list[SurveyResponse]:
    return list(
        db.scalars(
            select(SurveyResponse)
            .options(joinedload(SurveyResponse.survey))
            .where(SurveyResponse.owner_id == owner_id)
            .order_by(SurveyResponse.created_at.desc())
        )
    )


def response_by_id(db: Session, *, response_id: uuid.UUID) -> SurveyResponse | None:
    return db.get(SurveyResponse, response_id)


def gist(response: SurveyResponse) -> str:
    """The first typed answer, cut short."""
    for item in response.answers:
        text = str(item.get("text") or "")
        if text:
            return text if len(text) <= GIST_CHARS else text[:GIST_CHARS] + "…"
    return ""


def replied(db: Session, *, responses: Collection[SurveyResponse]) -> set[uuid.UUID]:
    """Which answers the office has written to the customer about since."""
    from app.modules.supportchat.selectors.conversations import office_wrote_at

    wrote = office_wrote_at(db, owner_ids=[row.owner_id for row in responses])
    return {
        row.id
        for row in responses
        if (moment := wrote.get(row.owner_id)) is not None and moment >= row.created_at
    }


def office_language(survey: Survey) -> str:
    return (
        OFFICE_LANGUAGE if survey.title.get(OFFICE_LANGUAGE) else survey.source_language
    )


def shown(row: SurveyQuestion, item: dict[str, Any], lang: str) -> str:
    """One answer as the office reads it."""
    if row.kind == QuestionKind.TEXT:
        return str(item.get("text") or "")
    if row.kind == QuestionKind.CHOICE:
        return ", ".join(
            row.options[pick].get(lang, "")
            for pick in item.get("choices") or []
            if isinstance(pick, int) and 0 <= pick < len(row.options)
        )
    number = item.get("number")
    return "" if number is None else f"{number} / {row.max_value}"


def answer_lines(db: Session, *, response: SurveyResponse) -> list[dict[str, Any]]:
    """Each answer kept, as it was read when it was given: the question and
    answer it carries win over today's wording, which may have been edited."""
    lang = office_language(response.survey)
    by_id = {str(row.id): row for row in questions_of(db, response.survey_id)}
    lines = []
    for item in response.answers:
        row = by_id.get(str(item.get("question")))
        if "q" in item:
            question, said = str(item.get("q") or ""), str(item.get("a") or "")
        elif row is not None:
            question, said = row.text.get(lang, ""), shown(row, item, lang)
        else:
            continue
        lines.append(
            {
                "question": question,
                "kind": str(item.get("kind") or (row.kind if row else "")),
                "answer": said or None,
                "removed": row is None,
            }
        )
    return lines
