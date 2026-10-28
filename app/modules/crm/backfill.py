"""Hands the Django project's one-CRM-per-owner rows out to the owner's pairs.

Run by migration 0006, and again by hand when needed:

    python -m app.modules.crm.backfill          # report only
    python -m app.modules.crm.backfill --apply  # write

Touches only rows whose ``page_id`` is still null, so a second run finds
nothing left to do. Nothing is deleted:

- the owner's setup, columns and lost reasons go to the pair the cabinet is
  on, keeping their ids; every other pair gets a copy of them;
- a card goes to its lead's pair, onto that pair's copy of its column and
  reason; the history follows the card;
- a manager goes to the pair they hold most cards in, else the cabinet's;
- a card no pair takes (Ads Manager campaigns, Meta's test leads) and an
  owner with no pair keep their nulls: off every board, still in the table.
"""

import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.crm.constants import StageKind
from app.modules.crm.models import (
    CrmCard,
    CrmLostReason,
    CrmMember,
    CrmSetup,
    CrmStage,
)
from app.modules.crm.selectors import Scope, pair_conditions
from app.modules.integrations.selectors import Pair, current_pair, page_pairs
from app.modules.leads.models import Lead

SETUP_COPIED = (
    "state",
    "step",
    "since",
    "leads_since",
    "every_ad",
    "ad_external_ids",
    "offered_ad_ids",
    "take_new_ads",
    "distribution",
    "currency",
    "enabled_at",
    "disabled_at",
    "created_at",
    "updated_at",
)
STAGE_COPIED = (
    "name",
    "color",
    "kind",
    "position",
    "counts_as_quality",
    "created_at",
    "updated_at",
)
REASON_COPIED = ("name", "position", "created_at", "updated_at")


@dataclass
class Report:
    owners: int = 0
    owners_without_pair: list[str] = field(default_factory=list)
    setups_copied: int = 0
    cards_placed: int = 0
    cards_left: int = 0
    members_placed: int = 0

    def summary(self) -> str:
        lines = [
            f"CRM juftliklarga: {self.owners} ta egasi, "
            f"{self.setups_copied} ta sozlama nusxasi, "
            f"{self.cards_placed} ta karta joylandi, "
            f"{self.members_placed} ta menejer joylandi, "
            f"{self.cards_left} ta karta hech bir juftlikka tushmadi (o'chirilmadi).",
        ]
        if self.owners_without_pair:
            lines.append(
                "Juftligi yo'q egalar (yozuvlari tegilmadi): "
                + ", ".join(self.owners_without_pair)
            )
        return "\n".join(lines)


def _copy(row: object, names: tuple[str, ...]) -> dict[str, object]:
    return {name: getattr(row, name) for name in names}


def _unplaced(db: Session, model: type[Any], owner_id: uuid.UUID) -> list[Any]:
    return list(
        db.scalars(
            select(model)
            .where(model.owner_id == owner_id, model.page_id.is_(None))
            .order_by(model.created_at)
        )
    )


def _card_pairs(
    db: Session, *, owner: User, pairs: list[Pair], card_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Pair]:
    """``{card id: its lead's pair}``; the first pair wins, as in placing."""
    conditions = pair_conditions(db, owner=owner, pairs=pairs)
    found: dict[uuid.UUID, Pair] = {}
    for pair in pairs:
        condition = conditions.get(pair.key)
        left = [card_id for card_id in card_ids if card_id not in found]
        if condition is None or not left:
            continue
        for card_id in db.scalars(
            select(CrmCard.id)
            .join(Lead, Lead.id == CrmCard.lead_id)
            .where(CrmCard.id.in_(left), condition)
        ):
            found.setdefault(card_id, pair)
    return found


def _onto_own(
    db: Session, *, scope: Scope, stages: list[Any], reasons: list[Any]
) -> tuple[dict[uuid.UUID, uuid.UUID], dict[uuid.UUID, uuid.UUID]]:
    """Old column and reason ids onto those of a pair that has a CRM already:
    the same kind and name, else the first of the kind, else its new column."""
    own = list(
        db.scalars(
            select(CrmStage).where(scope.holds(CrmStage)).order_by(CrmStage.position)
        )
    )
    first_new = next((s.id for s in own if s.kind == StageKind.NEW), None)
    stage_map: dict[uuid.UUID, uuid.UUID] = {}
    for stage in stages:
        same = next(
            (s.id for s in own if (s.kind, s.name) == (stage.kind, stage.name)), None
        )
        kind = next((s.id for s in own if s.kind == stage.kind), None)
        target = same or kind or first_new
        if target is not None:
            stage_map[stage.id] = target
    names = {
        reason.name: reason.id
        for reason in db.scalars(
            select(CrmLostReason).where(scope.holds(CrmLostReason))
        )
    }
    reason_map = {r.id: names[r.name] for r in reasons if r.name in names}
    return stage_map, reason_map


def _copies(
    db: Session, *, where: dict[str, uuid.UUID], stages: list[Any], reasons: list[Any]
) -> tuple[dict[uuid.UUID, uuid.UUID], dict[uuid.UUID, uuid.UUID]]:
    stage_map: dict[uuid.UUID, uuid.UUID] = {}
    for stage in stages:
        twin = CrmStage(**where, **_copy(stage, STAGE_COPIED))
        db.add(twin)
        db.flush()
        stage_map[stage.id] = twin.id
    reason_map: dict[uuid.UUID, uuid.UUID] = {}
    for reason in reasons:
        copy = CrmLostReason(**where, **_copy(reason, REASON_COPIED))
        db.add(copy)
        db.flush()
        reason_map[reason.id] = copy.id
    return stage_map, reason_map


def assign_owner(db: Session, *, owner: User, report: Report) -> None:
    setups = _unplaced(db, CrmSetup, owner.id)
    stages = _unplaced(db, CrmStage, owner.id)
    reasons = _unplaced(db, CrmLostReason, owner.id)
    members = _unplaced(db, CrmMember, owner.id)
    cards = _unplaced(db, CrmCard, owner.id)
    if not (setups or stages or reasons or members or cards):
        return
    report.owners += 1
    pairs = page_pairs(db, owner=owner)
    if not pairs:
        report.owners_without_pair.append(owner.email)
        report.cards_left += len(cards)
        return
    home = current_pair(db, owner=owner, pairs=pairs) or pairs[0]
    setup = setups[0] if setups else None
    # Read before any write: the updates below move these rows.
    card_rows = [(c.id, c.stage_id, c.lost_reason_id, c.assignee_id) for c in cards]
    member_rows = [(m.id, m.user_id) for m in members]
    by_card = _card_pairs(
        db, owner=owner, pairs=pairs, card_ids=[c[0] for c in card_rows]
    )

    held: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    for card_id, _stage, _reason, assignee_id in card_rows:
        if assignee_id is not None and card_id in by_card:
            held[assignee_id][by_card[card_id].key] += 1
    member_pair: dict[uuid.UUID, str] = {}
    for member_id, user_id in member_rows:
        counts = held.get(user_id)
        member_pair[member_id] = counts.most_common(1)[0][0] if counts else home.key

    placed_cards = 0
    for pair in pairs:
        scope = Scope.of(pair)
        where = scope.fields()
        has_own = (
            db.scalar(select(CrmSetup.id).where(scope.holds(CrmSetup))) is not None
        )
        if pair.key == home.key and not has_own:
            # The originals: their ids stay, so the audit log still finds them.
            stage_map = {stage.id: stage.id for stage in stages}
            reason_map = {reason.id: reason.id for reason in reasons}
            for model, rows in ((CrmStage, stages), (CrmLostReason, reasons)):
                if rows:
                    db.execute(
                        update(model)
                        .where(model.id.in_([row.id for row in rows]))
                        .values(**where, updated_at=model.updated_at)
                        .execution_options(synchronize_session=False)
                    )
            if setup is not None:
                db.execute(
                    update(CrmSetup)
                    .where(CrmSetup.id == setup.id)
                    .values(**where, updated_at=CrmSetup.updated_at)
                    .execution_options(synchronize_session=False)
                )
        elif has_own:
            stage_map, reason_map = _onto_own(
                db, scope=scope, stages=stages, reasons=reasons
            )
        else:
            stage_map, reason_map = _copies(
                db, where=where, stages=stages, reasons=reasons
            )
            if setup is not None:
                keeps = any(
                    member_pair[member_id] == pair.key
                    and user_id == setup.last_assigned_id
                    for member_id, user_id in member_rows
                )
                db.add(
                    CrmSetup(
                        **where,
                        **_copy(setup, SETUP_COPIED),
                        last_assigned_id=setup.last_assigned_id if keeps else None,
                    )
                )
                db.flush()
                report.setups_copied += 1
        for card_id, stage_id, reason_id, _assignee in card_rows:
            if by_card.get(card_id) != pair or stage_id not in stage_map:
                continue
            db.execute(
                update(CrmCard)
                .where(CrmCard.id == card_id)
                .values(
                    **where,
                    stage_id=stage_map[stage_id],
                    lost_reason_id=reason_map.get(reason_id) if reason_id else None,
                    updated_at=CrmCard.updated_at,
                )
                .execution_options(synchronize_session=False)
            )
            placed_cards += 1
        placed = [m for m, key in member_pair.items() if key == pair.key]
        if placed:
            db.execute(
                update(CrmMember)
                .where(CrmMember.id.in_(placed))
                .values(**where, updated_at=CrmMember.updated_at)
                .execution_options(synchronize_session=False)
            )
            report.members_placed += len(placed)
    report.cards_placed += placed_cards
    report.cards_left += len(card_rows) - placed_cards
    db.flush()
    db.expire_all()


def assign_pairs(db: Session) -> Report:
    """Every owner's unplaced CRM rows, handed out. Flushes; never commits."""
    report = Report()
    owner_ids: set[uuid.UUID] = set()
    for model in (CrmSetup, CrmStage, CrmLostReason, CrmMember, CrmCard):
        owner_ids |= set(
            db.scalars(select(model.owner_id).where(model.page_id.is_(None)).distinct())
        )
    for owner_id in sorted(owner_ids):
        owner = db.get(User, owner_id)
        if owner is not None:
            assign_owner(db, owner=owner, report=report)
    return report


def main(argv: list[str]) -> int:
    from app import models as _models  # noqa: F401
    from app.common.db import SessionLocal

    apply = "--apply" in argv
    with SessionLocal() as db:
        report = assign_pairs(db)
        print(report.summary())
        if apply:
            db.commit()
            print("Yozildi.")
        else:
            db.rollback()
            print("Faqat hisobot: yozish uchun --apply bering.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
