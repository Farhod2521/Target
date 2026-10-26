"""Writing down what one run decided to propose."""

from collections.abc import Mapping
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.agent.constants import SUGGESTION_TTL_HOURS
from app.modules.agent.diagnosed import diagnosis_of, diagnosis_record
from app.modules.agent.models import AgentRun, AgentSuggestion
from app.modules.agent.services.check_review import Reviewed
from app.modules.agent.services.retire_suggestions import supersede_suggestions
from core.agent.diagnosis import Diagnosis


def store_suggestions(
    db: Session,
    *,
    run: AgentRun,
    reviewed: list[Reviewed],
    now: datetime,
    causes: Mapping[str, Diagnosis] | None = None,
) -> list[AgentSuggestion]:
    """One row per surviving finding, with the numbers it was made from.

    Each row is its own savepoint: one the unique index refuses (the same
    object proposed twice in one night) is skipped, not the whole night.
    """
    expires_at = now + timedelta(hours=SUGGESTION_TTL_HOURS)
    stored: list[AgentSuggestion] = []
    for item in reviewed:
        finding = item.finding
        diagnosis = diagnosis_of(finding, causes or {})
        supersede_suggestions(
            db,
            owner=run.owner,
            target_external_id=finding.ref.id,
            rule=finding.rule,
            now=now,
        )
        row = AgentSuggestion(
            owner_id=run.owner_id,
            run_id=run.id,
            kind=finding.kind,
            rule=finding.rule,
            reason=item.reason,
            evidence=dict(finding.evidence),
            payload=dict(finding.payload),
            weight=finding.weight,
            expires_at=expires_at,
            target_provider=finding.ref.provider,
            target_level=finding.ref.level,
            target_external_id=finding.ref.id,
            target_parent_id=finding.parent_id,
            cause=diagnosis.cause if diagnosis is not None else "",
            diagnosis=diagnosis_record(diagnosis),
        )
        try:
            with db.begin_nested():
                db.add(row)
        except IntegrityError:
            continue
        stored.append(row)
    db.commit()
    return stored


__all__ = ["store_suggestions"]
