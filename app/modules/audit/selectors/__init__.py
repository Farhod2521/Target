from dataclasses import dataclass
from datetime import date, datetime

from llmkit import MICROS_PER_MINOR
from sqlalchemy import BigInteger, ColumnElement, case, func, select
from sqlalchemy.orm import Session

from app.modules.audit.constants import LLM_PURPOSE_LABELS, LLMCallStatus, LLMPurpose
from app.modules.audit.models import LLMCall

GATED_PURPOSES = (LLMPurpose.CHAT, LLMPurpose.REPORT, LLMPurpose.DAILY_REPORT)


def exact_cost() -> ColumnElement[int]:
    return case(
        (LLMCall.cost_micros == 0, LLMCall.cost_minor * MICROS_PER_MINOR),
        else_=LLMCall.cost_micros,
    ).cast(BigInteger)


def call_micros(call: LLMCall) -> int:
    return call.cost_micros or call.cost_minor * MICROS_PER_MINOR


def exact_minor(micros: int) -> str:
    whole, part = divmod(micros, MICROS_PER_MINOR)
    return f"{whole}.{part // 100:04d}"


@dataclass(frozen=True, slots=True)
class MaskingWeek:
    week: date
    purpose: str
    purpose_label: str
    answers: int
    masked_answers: int

    @property
    def share_pct(self) -> int:
        return round(self.masked_answers * 100 / self.answers) if self.answers else 0


def masking_by_week(db: Session, *, since: datetime) -> tuple[MaskingWeek, ...]:
    week = func.date_trunc("week", LLMCall.created_at)
    rows = db.execute(
        select(
            week.label("week"),
            LLMCall.purpose,
            func.count(LLMCall.id).label("answers"),
            func.count(LLMCall.id).filter(LLMCall.masked_figures > 0).label("masked"),
        )
        .where(
            LLMCall.created_at >= since,
            LLMCall.status == LLMCallStatus.OK,
            LLMCall.purpose.in_(GATED_PURPOSES),
        )
        .group_by(week, LLMCall.purpose)
        .order_by(week.desc(), func.count(LLMCall.id).desc())
    )
    return tuple(
        MaskingWeek(
            week=row.week.date(),
            purpose=str(row.purpose),
            purpose_label=str(LLM_PURPOSE_LABELS.get(row.purpose, row.purpose)),
            answers=row.answers,
            masked_answers=row.masked or 0,
        )
        for row in rows
    )


@dataclass(frozen=True, slots=True)
class PromptProfile:
    prompt_name: str
    prompt_version: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_minor: int
    cost_each_minor: int
    cost_micros: int
    cost_each_micros: int
    currency: str
    retried: int
    cut: int
    cached_tokens: int
    rounds: int
    tool_calls: int
    masked_answers: int

    @property
    def cost_exact(self) -> str:
        return exact_minor(self.cost_micros)

    @property
    def cost_each_exact(self) -> str:
        return exact_minor(self.cost_each_micros)


def prompt_profiles(
    db: Session, *, since: datetime, purpose: str = ""
) -> tuple[PromptProfile, ...]:
    cost = exact_cost()
    query = select(
        LLMCall.prompt_name,
        LLMCall.prompt_version,
        LLMCall.currency,
        func.count(LLMCall.id).label("calls"),
        func.avg(LLMCall.input_tokens).label("input_avg"),
        func.avg(LLMCall.output_tokens).label("output_avg"),
        func.sum(cost).label("spent"),
        func.count(LLMCall.id).filter(LLMCall.attempts > 1).label("retried"),
        func.count(LLMCall.id).filter(LLMCall.truncated > 0).label("cut"),
        func.avg(LLMCall.cache_read_tokens).label("cached_avg"),
        func.avg(cost).label("cost_avg"),
        func.avg(LLMCall.rounds).label("rounds_avg"),
        func.avg(LLMCall.tool_calls).label("tools_avg"),
        func.count(LLMCall.id).filter(LLMCall.masked_figures > 0).label("masked"),
    ).where(
        LLMCall.created_at >= since,
        LLMCall.status == LLMCallStatus.OK,
        LLMCall.input_tokens > 0,
    )
    if purpose:
        query = query.where(LLMCall.purpose == purpose)
    query = query.group_by(
        LLMCall.prompt_name, LLMCall.prompt_version, LLMCall.currency
    ).order_by(LLMCall.prompt_name, LLMCall.prompt_version.desc())
    return tuple(
        PromptProfile(
            prompt_name=row.prompt_name,
            prompt_version=row.prompt_version,
            calls=row.calls,
            input_tokens=round(row.input_avg or 0),
            output_tokens=round(row.output_avg or 0),
            cost_minor=int(row.spent or 0) // MICROS_PER_MINOR,
            cost_each_minor=round(row.cost_avg or 0) // MICROS_PER_MINOR,
            cost_micros=int(row.spent or 0),
            cost_each_micros=round(row.cost_avg or 0),
            currency=row.currency,
            retried=row.retried or 0,
            cut=row.cut or 0,
            cached_tokens=round(row.cached_avg or 0),
            rounds=round(row.rounds_avg or 0),
            tool_calls=round(row.tools_avg or 0),
            masked_answers=row.masked or 0,
        )
        for row in db.execute(query)
    )


__all__ = [
    "GATED_PURPOSES",
    "MaskingWeek",
    "PromptProfile",
    "call_micros",
    "exact_cost",
    "exact_minor",
    "masking_by_week",
    "prompt_profiles",
]
