"""The boards' deadlines and three more columns.

`board_cards.due_at`: the time the person working a card set for its next
step. `board_cards.attempts`: how many times «Bog'lanilmadi» was pressed.

Columns: Sales gets «Qayta aloqa» after Bog'lanildi and «To'lov kutilmoqda»
before Sotildi; Support gets «Mijoz kutilmoqda» after Ishlanmoqda. Each is
put right after its neighbour in the order the office keeps now, and the
columns after it move one place on.

Additive and idempotent: columns with defaults, and a board row that is
there already is left alone.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | Sequence[str] | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# board, code, name, kind, the column it stands after.
NEW_COLUMNS = (
    ("sales", "callback", "Qayta aloqa", "manual", "contacted"),
    ("sales", "awaiting", "To'lov kutilmoqda", "auto", "no_discount"),
    ("support", "waiting", "Mijoz kutilmoqda", "manual", "in_progress"),
)


def _add(
    conn: sa.Connection, board: str, code: str, name: str, kind: str, after: str
) -> None:
    rows = dict(
        conn.execute(
            sa.text("SELECT code, position FROM board_columns WHERE board = :b"),
            {"b": board},
        ).all()
    )
    # No rows: the board was never seeded here, and the first read seeds it whole.
    if not rows or code in rows:
        return
    at = rows.get(after, max(rows.values()))
    conn.execute(
        sa.text(
            "UPDATE board_columns SET position = position + 1 "
            "WHERE board = :b AND position > :at"
        ),
        {"b": board, "at": at},
    )
    conn.execute(
        sa.text(
            "INSERT INTO board_columns (id, created_at, updated_at, board, code, "
            "name, position, kind, is_final, is_visible) VALUES "
            "(:id, now(), now(), :b, :code, :name, :position, :kind, false, true)"
        ),
        {
            "id": uuid.uuid4(),
            "b": board,
            "code": code,
            "name": name,
            "position": at + 1,
            "kind": kind,
        },
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE board_cards ADD COLUMN IF NOT EXISTS due_at timestamptz NULL"
    )
    op.execute(
        "ALTER TABLE board_cards "
        "ADD COLUMN IF NOT EXISTS attempts smallint NOT NULL DEFAULT 0"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS board_cards_due_idx ON board_cards (board, due_at) "
        "WHERE due_at IS NOT NULL"
    )
    conn = op.get_bind()
    for column in NEW_COLUMNS:
        _add(conn, *column)


def downgrade() -> None:
    conn = op.get_bind()
    # A card standing in a column that goes away steps back to its neighbour.
    for board, code, _name, _kind, after in NEW_COLUMNS:
        conn.execute(
            sa.text(
                "UPDATE board_cards SET column_code = :after "
                "WHERE board = :b AND column_code = :code"
            ),
            {"b": board, "code": code, "after": after},
        )
        at = conn.execute(
            sa.text(
                "DELETE FROM board_columns WHERE board = :b AND code = :code "
                "RETURNING position"
            ),
            {"b": board, "code": code},
        ).scalar()
        if at is not None:
            conn.execute(
                sa.text(
                    "UPDATE board_columns SET position = position - 1 "
                    "WHERE board = :b AND position > :at"
                ),
                {"b": board, "at": at},
            )
    op.execute("DROP INDEX IF EXISTS board_cards_due_idx")
    op.execute("ALTER TABLE board_cards DROP COLUMN IF EXISTS attempts")
    op.execute("ALTER TABLE board_cards DROP COLUMN IF EXISTS due_at")
