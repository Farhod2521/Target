"""Holding the model's review to what it was asked, and paying for what it cost."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from llmkit import LLMError, LLMResult, Spend, StructuredOutputError
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.llm import UNATTENDED, both, model_for, prompts
from app.modules.accounts.models import User
from app.modules.agent.constants import RUN_RELATED_TYPE
from app.modules.audit.constants import LLMPurpose
from app.modules.audit.services import record_llm_error
from core.agent import AgentReview, DecisionNote, Finding
from core.chat.verify import FigureGate

PROMPT: Final = "agent_review"
SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class Reviewed:
    """One finding, with the model's verdict and its sentence."""

    finding: Finding
    reason: str
    keep: bool


def numbered(client: Any, *, ask: Mapping[str, Any], size: int) -> Any:
    """One part's answer, whose notes are numbered as the entries were."""
    first = client.structured(**ask)
    if in_order(first.value.notes, size):
        return first
    second = client.structured(**ask)
    paid = both(first, second)
    if in_order(second.value.notes, size):
        return paid
    raise StructuredOutputError(
        "review notes are not numbered 0..n-1",
        schema=AgentReview.__name__,
        attempts=paid.attempts,
        spent=spent_with(Spend(), paid),
    )


def in_order(notes: list[DecisionNote], size: int) -> bool:
    indices = [note.index for note in notes]
    return len(set(indices)) == len(indices) and all(
        0 <= index < size for index in indices
    )


def spent_with(spent: Spend, result: LLMResult[Any]) -> Spend:
    """What a failure cost, with the parts answered before it."""
    return Spend(
        input_tokens=spent.input_tokens + result.input_tokens,
        output_tokens=spent.output_tokens + result.output_tokens,
        cache_write_tokens=spent.cache_write_tokens + result.cache_write_tokens,
        cache_read_tokens=spent.cache_read_tokens + result.cache_read_tokens,
        cost_micros=spent.cost_micros + result.cost_micros,
    )


def record_failure(db: Session, *, owner: User, run_id: UUID, exc: LLMError) -> int:
    """The ledger row for a review that came back unusable, or not at all."""
    record_llm_error(
        db,
        owner=owner,
        purpose=LLMPurpose.DECISION,
        exc=exc,
        prompt_name=PROMPT,
        prompt_version=prompts().latest(PROMPT),
        model=model_for(UNATTENDED),
        currency=str(settings.anthropic_price_currency),
        related_type=RUN_RELATED_TYPE,
        related_id=run_id,
    )
    return exc.spent.cost_minor


def checked_reason(reason: str, allowed: frozenset[str]) -> str:
    """The reason without any sentence that names a figure nobody supplied."""
    kept = []
    for sentence in SENTENCE_END.split(reason.strip()):
        gate = FigureGate(allowed=allowed)
        gate.feed(sentence)
        gate.flush()
        if sentence and gate.masked == 0:
            kept.append(sentence)
    return " ".join(kept)


def merged(
    *,
    findings: list[Finding],
    notes: list[DecisionNote],
    allowed: frozenset[str] = frozenset(),
) -> list[Reviewed]:
    """The model's notes matched back to the findings they describe."""
    by_index = {note.index: note for note in notes}
    return [
        Reviewed(
            finding=finding,
            reason=checked_reason(note.reason, allowed) if note is not None else "",
            keep=note.keep if note is not None else True,
        )
        for finding, note in (
            (finding, by_index.get(index)) for index, finding in enumerate(findings)
        )
    ]


__all__ = [
    "Reviewed",
    "checked_reason",
    "in_order",
    "merged",
    "numbered",
    "record_failure",
    "spent_with",
]
