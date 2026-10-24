"""One week's report: the numbers now, the sentence when a worker has it."""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from llmkit import LLMError, render
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.exceptions import LLMUnavailable
from app.common.i18n import override
from app.common.llm import UNATTENDED, claude, model_for, prompts
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMPurpose
from app.modules.chat.constants import (
    REPORT_PROMPT_NAME,
    REPORT_RELATED_TYPE,
    REPORT_TTL_SECONDS,
    TURN_TTL_SECONDS,
)
from app.modules.chat.services.daily import about
from core.chat.report import WeeklyReport
from core.chat.verify import FigureGate
from core.chat.week_review import WeekReview

logger = logging.getLogger(__name__)

KEY: Final = "chat:report:{owner}:{digest}"

RUNNING: Final = "running"
DONE: Final = "done"
FAILED: Final = "failed"


@dataclass(frozen=True, slots=True)
class Comment:
    """The sentence under a week, and whether one is still on its way."""

    text: str = ""
    masked: int = 0
    is_pending: bool = False
    advice: str = ""


def report_digest(*, report: WeeklyReport) -> str:
    """The week's fingerprint: a digest of the text handed to the model."""
    return hashlib.sha256(report.render().encode("utf-8")).hexdigest()[:16]


def report_key(*, owner: User, report: WeeklyReport) -> str:
    return KEY.format(owner=owner.id, digest=report_digest(report=report))


def comment_for(*, owner: User, report: WeeklyReport) -> Comment:
    """What the screen shows under the figures, without waiting for anything."""
    state = cache.get(report_key(owner=owner, report=report))
    if not isinstance(state, dict):
        return Comment()
    if state.get("state") == DONE:
        return Comment(
            text=str(state.get("text", "")),
            masked=int(state.get("masked", 0)),
            advice=str(state.get("advice", "")),
        )
    return Comment(is_pending=state.get("state") == RUNNING)


def claim_week(*, owner: User, report: WeeklyReport) -> bool:
    """Reserve this week for one worker. ``True`` when the caller should queue."""
    return bool(
        cache.add(
            report_key(owner=owner, report=report), {"state": RUNNING}, TURN_TTL_SECONDS
        )
    )


def request_comment(*, owner: User, report: WeeklyReport) -> tuple[Comment, bool]:
    """The comment now, and whether the caller should start a worker."""
    comment = comment_for(owner=owner, report=report)
    if comment.text or comment.is_pending or not report.wants_sentence:
        return comment, False
    if claim_week(owner=owner, report=report):
        return Comment(is_pending=True), True
    return comment_for(owner=owner, report=report), False


def explain_week(db: Session, *, owner: User, now: datetime, pair: str = "") -> None:
    """Ask Claude for the reading of one pair's week, and cache it."""
    from app.modules.chat.selectors.report import weekly_report

    with override(owner.language):
        report = weekly_report(db, owner=owner, now=now, pair=pair)
        if report is None or not report.wants_sentence:
            return
        _ask(db, owner=owner, report=report, now=now)


def _ask(db: Session, *, owner: User, report: WeeklyReport, now: datetime) -> None:
    from app.modules.audit.services import record_llm_error, record_llm_result
    from app.modules.billing.selectors import ai_budget

    key = report_key(owner=owner, report=report)
    if ai_budget(db, owner=owner, now=now).chat_is_exhausted:
        cache.set(key, {"state": FAILED}, TURN_TTL_SECONDS)
        return
    related_id = report_digest(report=report)
    template, version = prompts().get(REPORT_PROMPT_NAME)
    try:
        with claude(tier=UNATTENDED) as client:
            result = client.structured(
                prompt=report.render(),
                schema=WeekReview,
                prompt_name=REPORT_PROMPT_NAME,
                prompt_version=version,
                system=render(template, {}).rstrip(),
                system_tail=about(db, owner, page_id=report.page_id),
            )
    except LLMUnavailable:
        logger.warning("weekly report skipped: no Claude in this process")
        cache.set(key, {"state": FAILED}, TURN_TTL_SECONDS)
        return
    except LLMError as exc:
        logger.warning("weekly report failed: %s", exc)
        cache.set(key, {"state": FAILED}, TURN_TTL_SECONDS)
        record_llm_error(
            db,
            owner=owner,
            purpose=LLMPurpose.REPORT,
            exc=exc,
            prompt_name=REPORT_PROMPT_NAME,
            prompt_version=version,
            model=model_for(UNATTENDED),
            currency=str(settings.anthropic_price_currency),
            related_type=REPORT_RELATED_TYPE,
            related_id=related_id,
        )
        return
    gate = FigureGate(allowed=report.figures())
    summary = (gate.feed(result.value.summary) + gate.flush()).strip()
    advice = (gate.feed(result.value.advice) + gate.flush()).strip()
    cache.set(
        key,
        {"state": DONE, "text": summary, "advice": advice, "masked": gate.masked},
        REPORT_TTL_SECONDS,
    )
    record_llm_result(
        db,
        owner=owner,
        purpose=LLMPurpose.REPORT,
        result=result,
        masked=gate.masked,
        related_type=REPORT_RELATED_TYPE,
        related_id=related_id,
    )


def cached_state(*, owner: User, report: WeeklyReport) -> dict[str, Any] | None:
    """The raw entry, for a caller that needs more than :class:`Comment`."""
    state = cache.get(report_key(owner=owner, report=report))
    return state if isinstance(state, dict) else None


__all__ = [
    "Comment",
    "cached_state",
    "claim_week",
    "comment_for",
    "explain_week",
    "report_digest",
    "report_key",
    "request_comment",
]
