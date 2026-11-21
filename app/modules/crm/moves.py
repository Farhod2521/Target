"""The steps a card takes across the board, written as it takes them.

A card changes column in many places - a manager drags it, takes it, sells
it, the customer writes again, a manager is removed - and a place added
later would be one more to forget. So the step is not written by those
places: a listener on the session writes it at every flush, from the
card's own change. A new card gets its arriving row, a card whose column
changed gets one row from the old column to the new.

One thing goes around the session: a column deleted by its owner moves its
cards with a single UPDATE. ``record_swept`` writes those steps.

The cards that were on the boards before this table existed have no rows.
``rebuild`` puts theirs together from the card's history lines and marks
them ``rebuilt``:

    python -m app.modules.crm.moves          # report only
    python -m app.modules.crm.moves --apply  # write the rows
"""

import sys
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.crm.constants import ActivityKind, StageKind
from app.modules.crm.models.crm import CrmActivity, CrmCard, CrmStage, CrmStageMove


def _kind(session: Session, stage_id: uuid.UUID | None) -> str:
    if stage_id is None:
        return ""
    stage = session.get(CrmStage, stage_id)
    return stage.kind if stage is not None else ""


@event.listens_for(Session, "before_flush")
def _record(session: Session, _context: Any, _instances: Any) -> None:
    steps: list[tuple[CrmCard, uuid.UUID | None, uuid.UUID]] = []
    for row in session.new:
        if isinstance(row, CrmCard) and row.stage_id is not None:
            steps.append((row, None, row.stage_id))
    for row in session.dirty:
        if not isinstance(row, CrmCard):
            continue
        change = inspect(row).attrs.stage_id.history
        if not change.has_changes() or not change.added:
            continue
        left = change.deleted[0] if change.deleted else None
        entered = change.added[0]
        if entered is not None and entered != left:
            steps.append((row, left, entered))
    now = utcnow()
    for card, left, entered in steps:
        session.add(
            CrmStageMove(
                owner_id=card.owner_id,
                card=card,
                from_stage_id=left,
                from_kind=_kind(session, left),
                to_stage_id=entered,
                to_kind=_kind(session, entered),
                at=now,
            )
        )


def record_swept(
    db: Session, *, left: CrmStage, entered: CrmStage, now: datetime
) -> int:
    """The steps of every card standing in ``left``, about to be moved to
    ``entered`` by one UPDATE the session does not see."""
    cards = db.execute(
        select(CrmCard.id, CrmCard.owner_id).where(CrmCard.stage_id == left.id)
    ).all()
    for card_id, owner_id in cards:
        db.add(
            CrmStageMove(
                owner_id=owner_id,
                card_id=card_id,
                from_stage_id=left.id,
                from_kind=left.kind,
                to_stage_id=entered.id,
                to_kind=entered.kind,
                at=now,
            )
        )
    return len(cards)


# -- the cards that were here before the table --

_CLOSING = {
    ActivityKind.WON: StageKind.WON,
    ActivityKind.LOST: StageKind.LOST,
    ActivityKind.UNQUALIFIED: StageKind.JUNK,
}
_CLOSED = (StageKind.WON, StageKind.LOST, StageKind.JUNK)


def _named(stages: list[CrmStage], name: str) -> CrmStage | None:
    """The column a history line names. A line of a removed manager ends in
    his name in brackets: «A → B (Ali)»."""
    for candidate in (name, name.rpartition(" (")[0]):
        for stage in stages:
            if candidate and stage.name == candidate:
                return stage
    return None


def _of_kind(stages: list[CrmStage], kind: str) -> CrmStage | None:
    return next((stage for stage in stages if stage.kind == kind), None)


def steps_of(
    card: CrmCard,
    *,
    stages: list[CrmStage],
    history: list[CrmActivity],
    measured: CrmStageMove | None = None,
) -> list[tuple[CrmStage | None, CrmStage, datetime]]:
    """A card's steps as its history tells them, oldest first.

    A line that names a column the board no longer has is passed over. The
    last step always ends where the card stands now: when the history does
    not lead there, one more step is added at the card's last change.

    ``measured`` is the card's first step written as it happened, for a card
    that moved between the table arriving and this running: the history is
    then read only up to that step, and ends in the column it left.
    """
    first = _of_kind(stages, StageKind.NEW)
    by_id = {stage.id: stage for stage in stages}
    if measured is not None:
        history = [line for line in history if line.created_at < measured.at]
        now_at = by_id.get(measured.from_stage_id) if measured.from_stage_id else None
        ends_at = measured.at
    else:
        now_at = by_id.get(card.stage_id)
        ends_at = card.updated_at
    if first is None or now_at is None:
        return []
    steps: list[tuple[CrmStage | None, CrmStage, datetime]] = [
        (None, first, card.created_at)
    ]
    here = first
    for line in history:
        entered: CrmStage | None = None
        if line.kind == ActivityKind.MOVED:
            entered = _named(stages, line.text.partition(" → ")[2])
        elif line.kind == ActivityKind.TAKEN:
            entered = _named(stages, line.text)
        elif line.kind in _CLOSING:
            entered = _of_kind(stages, _CLOSING[ActivityKind(line.kind)])
        elif line.kind == ActivityKind.RETURNED and here.kind in _CLOSED:
            # A customer who writes again after a closed card reopens it.
            entered = first
        if entered is not None and entered.id != here.id:
            steps.append((here, entered, line.created_at))
            here = entered
    if here.id != now_at.id:
        # For a measured card the join is put just before its first true
        # step, so the two never share an instant.
        at = ends_at if measured is None else ends_at - timedelta(microseconds=1)
        steps.append((here, now_at, max(at, steps[-1][2])))
    return steps


def rebuild(db: Session, *, apply: bool, batch: int = 500) -> tuple[int, int]:
    """Rows for every card that lacks its arriving one; (cards, rows). Safe
    to run again: a card whose steps begin with its arrival is never touched.

    A card that moved after the table arrived and before this ran has its
    later steps and not its earlier ones; those are filled in up to the
    first step written as it happened."""
    arrived = select(CrmStageMove.card_id).where(
        CrmStageMove.card_id == CrmCard.id, CrmStageMove.from_stage_id.is_(None)
    )
    cards = list(db.scalars(select(CrmCard).where(~arrived.exists())))
    boards: dict[tuple[Any, Any, Any], list[CrmStage]] = {}
    done = rows = 0
    for card in cards:
        key = (card.owner_id, card.page_id, card.ad_account_id)
        if key not in boards:
            boards[key] = list(
                db.scalars(
                    select(CrmStage)
                    .where(
                        CrmStage.owner_id == card.owner_id,
                        CrmStage.page_id.is_not_distinct_from(card.page_id),
                        CrmStage.ad_account_id.is_not_distinct_from(card.ad_account_id),
                    )
                    .order_by(CrmStage.position)
                )
            )
        history = list(
            db.scalars(
                select(CrmActivity)
                .where(CrmActivity.card_id == card.id)
                .order_by(CrmActivity.created_at, CrmActivity.id)
            )
        )
        measured = db.scalars(
            select(CrmStageMove)
            .where(CrmStageMove.card_id == card.id)
            .order_by(CrmStageMove.at, CrmStageMove.created_at)
            .limit(1)
        ).first()
        steps = steps_of(card, stages=boards[key], history=history, measured=measured)
        if not steps:
            continue
        done += 1
        rows += len(steps)
        if not apply:
            continue
        for left, entered, at in steps:
            db.add(
                CrmStageMove(
                    owner_id=card.owner_id,
                    card_id=card.id,
                    from_stage_id=left.id if left else None,
                    from_kind=left.kind if left else "",
                    to_stage_id=entered.id,
                    to_kind=entered.kind,
                    at=at,
                    rebuilt=True,
                )
            )
        if done % batch == 0:
            db.commit()
    if apply:
        db.commit()
    return done, rows


def main() -> None:
    from app.worker import task_session

    apply = "--apply" in sys.argv
    with task_session() as db:
        cards, rows = rebuild(db, apply=apply)
    print(f"cards: {cards}, steps: {rows}, {'written' if apply else 'report only'}")


if __name__ == "__main__":
    main()
