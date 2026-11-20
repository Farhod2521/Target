"""Where the sales process stands: each column's cards now, and how long
cards stay in it.

Read from the steps kept in ``crm_stage_moves``. A card's stay in a column
runs from the step that brought it there to the step that took it away; a
card with no later step is standing there still, and its wait runs to now.

Two different waits, never mixed: ``waiting_min`` is about the cards in the
column at this moment - how long the middle one has stood - and ``stay_min``
is about the stays that ended inside the range - how long the column
usually holds a card before it moves on. A column that only collects has
the first and not the second.

A stay built from ``rebuilt`` steps has a history line's time, not a
measured one; ``approximate`` says the column's figures lean on such stays.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.crm.constants import StageKind
from app.modules.crm.models import CrmCard, CrmStage, CrmStageMove
from app.modules.crm.selectors import Viewer, holds, stages_of
from app.modules.crm.selectors.stats import Range
from core.metrics.formulas import typical_minutes

_CLOSED = (StageKind.WON, StageKind.LOST, StageKind.JUNK)


@dataclass(slots=True)
class StageProcess:
    stage: CrmStage
    # Cards standing in the column now.
    now: int = 0
    # Of those, the ones whose due time has passed.
    late: int = 0
    # Minutes the cards standing here have stood, each one. Empty for a
    # closing column: a card sold or refused is not waiting.
    waiting: list[float] = field(default_factory=list)
    # Minutes of the stays that ended in the range, each one.
    stays: list[float] = field(default_factory=list)
    approximate: bool = False

    @property
    def waiting_min(self) -> int | None:
        return typical_minutes(self.waiting)

    @property
    def longest_wait_min(self) -> int | None:
        return round(max(self.waiting)) if self.waiting else None

    @property
    def stay_min(self) -> int | None:
        return typical_minutes(self.stays)


def process(
    db: Session, *, viewer: Viewer, span: Range, now: datetime
) -> list[StageProcess]:
    """One row for each column of the board, in the board's order."""
    stages = stages_of(db, scope=viewer.scope)
    found = {stage.id: StageProcess(stage=stage) for stage in stages}
    if viewer.scope is None or not found:
        return list(found.values())
    start, end = span.bounds()
    left_at = func.lead(CrmStageMove.at).over(
        partition_by=CrmStageMove.card_id,
        order_by=(CrmStageMove.at, CrmStageMove.created_at),
    )
    steps = db.execute(
        select(
            CrmStageMove.card_id,
            CrmStageMove.to_stage_id,
            CrmStageMove.at,
            CrmStageMove.rebuilt,
            left_at,
        )
        .join(CrmCard, CrmCard.id == CrmStageMove.card_id)
        .where(holds(viewer.scope, CrmCard))
    )
    # Where each card stands and since when: its last step, if that step
    # leads to the column the card is in now.
    entered: dict[uuid.UUID, tuple[uuid.UUID, datetime]] = {}
    for card_id, stage_id, at, rebuilt, left in steps:
        row = found.get(stage_id)
        if left is None:
            entered[card_id] = (stage_id, at)
            if row is not None and rebuilt:
                row.approximate = True
            continue
        if row is None or left < at or not (start <= left < end):
            continue
        row.stays.append((left - at).total_seconds() / 60)
        row.approximate = row.approximate or rebuilt
    cards = db.execute(
        select(CrmCard.id, CrmCard.stage_id, CrmCard.due_at, CrmCard.closed_at).where(
            holds(viewer.scope, CrmCard)
        )
    )
    for card_id, stage_id, due_at, closed_at in cards:
        row = found.get(stage_id)
        if row is None:
            continue
        row.now += 1
        row.late += closed_at is None and due_at is not None and due_at < now
        step = entered.get(card_id)
        # A card with no step of its own yet (the rebuild has not run) is
        # counted and not timed.
        if row.stage.kind in _CLOSED:
            # A closed card is not waiting for anybody.
            continue
        if step is not None and step[0] == stage_id and step[1] <= now:
            row.waiting.append((now - step[1]).total_seconds() / 60)
    return list(found.values())


__all__ = ["StageProcess", "process"]
