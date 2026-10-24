"""Claude's reading of one day, for the evening message on the phone."""

import logging
from datetime import datetime

from llmkit import LLMError, LLMResult, render
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.exceptions import LLMUnavailable
from app.common.i18n import get_language
from app.common.llm import UNATTENDED, claude, model_for, prompts
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMPurpose
from app.modules.chat.constants import DAILY_PROMPT_NAME, DAILY_RELATED_TYPE
from core.chat.daily import DailyReport, settled
from core.chat.day_review import CampaignNote, DayReview
from core.chat.verify import FigureGate

logger = logging.getLogger(__name__)


def review_day(
    db: Session, *, owner: User, report: DailyReport, now: datetime
) -> DayReview | None:
    """The day read by Claude, or nothing when it could not or should not be."""
    from app.modules.audit.services import record_llm_result
    from app.modules.billing.selectors import ai_budget

    if report.is_quiet or not report.campaigns:
        return None
    if ai_budget(db, owner=owner, now=now).chat_is_exhausted:
        return None
    result = _ask(db, owner=owner, report=report)
    if result is None:
        return None
    gate = FigureGate(allowed=report.figures())
    reading = gated(result.value, report=report, gate=gate)
    record_llm_result(
        db,
        owner=owner,
        purpose=LLMPurpose.DAILY_REPORT,
        result=result,
        masked=gate.masked,
        related_type=DAILY_RELATED_TYPE,
        related_id=_reading_of(report),
    )
    return reading


def _reading_of(report: DailyReport) -> str:
    return (
        f"{report.day.isoformat()}:{report.pair}"
        if report.pair
        else report.day.isoformat()
    )


def _ask(
    db: Session, *, owner: User, report: DailyReport
) -> LLMResult[DayReview] | None:
    """The one call. A failure is recorded and answered with nothing."""
    from app.modules.audit.services import record_llm_error

    template, version = prompts().get(DAILY_PROMPT_NAME)
    try:
        with claude(tier=UNATTENDED) as client:
            return client.structured(
                prompt=report.render(),
                schema=DayReview,
                prompt_name=DAILY_PROMPT_NAME,
                prompt_version=version,
                system=render(template, {}).rstrip(),
                system_tail=about(db, owner, page_id=report.page_id),
            )
    except LLMUnavailable:
        logger.warning("daily report reading skipped: no Claude in this process")
    except LLMError as exc:
        logger.warning("daily report reading failed: %s", exc)
        record_llm_error(
            db,
            owner=owner,
            purpose=LLMPurpose.DAILY_REPORT,
            exc=exc,
            prompt_name=DAILY_PROMPT_NAME,
            prompt_version=version,
            model=model_for(UNATTENDED),
            currency=str(settings.anthropic_price_currency),
            related_type=DAILY_RELATED_TYPE,
            related_id=_reading_of(report),
        )
    return None


def about(db: Session, owner: User, *, page_id: str) -> str:
    """The language to answer in, and who the business is. Nothing else."""
    from app.modules.businesses.selectors import business_for_page_id, category_label

    lines = [f"Answer in: {get_language() or owner.language}"]
    business = business_for_page_id(db, owner=owner, page_id=page_id)
    if business is not None:
        trade = category_label(business)
        lines += [
            "",
            "## The business",
            f"- Nomi: {business.name}",
            f"- Sohasi: {trade}",
            f"- Nima sotadi: {business.offer_text or trade}",
        ]
    return "\n".join(lines)


def gated(
    review: DayReview, *, report: DailyReport, gate: FigureGate | None = None
) -> DayReview:
    """The reading with every figure the report did not supply removed."""
    shared = gate if gate is not None else FigureGate(allowed=report.figures())
    return DayReview.model_construct(
        summary=_safe(review.summary, shared),
        notes=[
            CampaignNote.model_construct(
                index=note.index,
                verdict=settled(note.verdict, campaign=report.campaigns[note.index]),
                line=_safe(note.line, shared),
            )
            for note in _one_per_campaign(review.notes, size=len(report.campaigns))
        ],
        advice=_safe(review.advice, shared),
    )


def _one_per_campaign(notes: list[CampaignNote], *, size: int) -> list[CampaignNote]:
    seen: set[int] = set()
    kept: list[CampaignNote] = []
    for note in notes:
        if note.index < size and note.index not in seen:
            seen.add(note.index)
            kept.append(note)
    return kept


def _safe(text: str, gate: FigureGate) -> str:
    return (gate.feed(text) + gate.flush()).strip()


__all__ = ["about", "gated", "review_day"]
