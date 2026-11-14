"""What became of each reason on a Support ticket, read back from history.

A ticket's reasons were only ever added. From now on «Hal qilindi» solves
every open one, and the client's «Yo'q» or a reopening by hand opens that
round again; this writes the same state onto the tickets that are there
already, by replaying each ticket's own history lines in order:

- `resolved`: every reason raised by then and still open is solved, with
  who pressed it and what they wrote;
- `denied` (the client's no): that round is open again, marked as denied;
- `reopened` by a person and with no new reason: that round is open again.

Only keys are added inside `board_cards.reasons`; nothing is deleted. The
downgrade takes those keys off.
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = ("solved_at", "solved_by", "solved_note", "denied_at")


def replay(reasons: list[dict[str, Any]], events: list[dict[str, Any]]) -> bool:
    """Write each reason's state from the ticket's lines, oldest first.
    Whether anything changed."""
    changed = False
    last = ""
    for event in events:
        at = event["at"]
        if event["kind"] == "resolved":
            for item in reasons:
                if not item.get("solved_at") and str(item.get("at", "")) <= at:
                    item["solved_at"] = at
                    item["solved_by"] = event["by"]
                    item["solved_note"] = event["body"]
                    item.pop("denied_at", None)
                    changed = True
            last = at
        elif last and (
            event["kind"] == "denied"
            or (event["kind"] == "reopened" and event["by"] and not event["ref"])
        ):
            for item in reasons:
                if item.get("solved_at") == last:
                    for key in ("solved_at", "solved_by", "solved_note"):
                        item.pop(key, None)
                    if event["kind"] == "denied":
                        item["denied_at"] = at
                    changed = True
            last = ""
    return changed


def upgrade() -> None:
    conn = op.get_bind()
    cards = conn.execute(
        sa.text(
            "SELECT id, reasons FROM board_cards "
            "WHERE board = 'support' AND jsonb_array_length(reasons) > 0"
        )
    ).all()
    for card_id, reasons in cards:
        events = [
            {
                # The same shape the reasons' own `at` is written in.
                "at": created_at.isoformat(),
                "kind": kind,
                "body": body or "",
                "ref": ref or "",
                "by": who or "",
            }
            for created_at, kind, body, ref, who in conn.execute(
                sa.text(
                    "SELECT e.created_at, e.kind, e.body, e.ref, "
                    "COALESCE(NULLIF(u.full_name, ''), u.email) "
                    "FROM board_card_events e LEFT JOIN users u ON u.id = e.actor_id "
                    "WHERE e.card_id = :card AND e.kind IN "
                    "('resolved', 'denied', 'reopened') ORDER BY e.created_at, e.id"
                ),
                {"card": card_id},
            )
        ]
        items = [dict(item) for item in reasons]
        if events and replay(items, events):
            conn.execute(
                sa.text(
                    "UPDATE board_cards SET reasons = CAST(:reasons AS jsonb) "
                    "WHERE id = :card"
                ),
                {"reasons": json.dumps(items, ensure_ascii=False), "card": card_id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    cards = conn.execute(
        sa.text(
            "SELECT id, reasons FROM board_cards "
            "WHERE board = 'support' AND jsonb_array_length(reasons) > 0"
        )
    ).all()
    for card_id, reasons in cards:
        items = [{k: v for k, v in item.items() if k not in KEYS} for item in reasons]
        if items != list(reasons):
            conn.execute(
                sa.text(
                    "UPDATE board_cards SET reasons = CAST(:reasons AS jsonb) "
                    "WHERE id = :card"
                ),
                {"reasons": json.dumps(items, ensure_ascii=False), "card": card_id},
            )
