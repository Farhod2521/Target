"""Three more Support columns.

«Dasturchiga berildi» after Mijoz kutilmoqda; «Tasdiq kutilmoqda» after it:
Support called the ticket solved and the client is asked whether it is;
«Yopildi» after Hal qilindi: the client did not answer in time. Each is put
right after its neighbour in the order the office keeps now, and the
columns after it move one place on.

Hal qilindi is reached by the client's yes now, not by a button, so its
kind becomes `auto`.

Additive and idempotent: a board row that is there already is left alone,
and no card is moved.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# code, name, kind, final, the column it stands after, where its cards go
# when it is taken away.
NEW_COLUMNS = (
    ("developer", "Dasturchiga berildi", "manual", False, "waiting", "in_progress"),
    ("confirming", "Tasdiq kutilmoqda", "manual", False, "developer", "in_progress"),
    ("closed", "Yopildi", "auto", True, "resolved", "resolved"),
)
BOARD = "support"


def _add(
    conn: sa.Connection, code: str, name: str, kind: str, final: bool, after: str
) -> None:
    rows = dict(
        conn.execute(
            sa.text("SELECT code, position FROM board_columns WHERE board = :b"),
            {"b": BOARD},
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
        {"b": BOARD, "at": at},
    )
    conn.execute(
        sa.text(
            "INSERT INTO board_columns (id, created_at, updated_at, board, code, "
            "name, position, kind, is_final, is_visible) VALUES "
            "(:id, now(), now(), :b, :code, :name, :position, :kind, :final, true)"
        ),
        {
            "id": uuid.uuid4(),
            "b": BOARD,
            "code": code,
            "name": name,
            "position": at + 1,
            "kind": kind,
            "final": final,
        },
    )


def upgrade() -> None:
    conn = op.get_bind()
    for code, name, kind, final, after, _back in NEW_COLUMNS:
        _add(conn, code, name, kind, final, after)
    conn.execute(
        sa.text(
            "UPDATE board_columns SET kind = 'auto' "
            "WHERE board = :b AND code = 'resolved'"
        ),
        {"b": BOARD},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE board_columns SET kind = 'manual' "
            "WHERE board = :b AND code = 'resolved'"
        ),
        {"b": BOARD},
    )
    # A card standing in a column that goes away steps back.
    for code, _name, _kind, _final, _after, back in NEW_COLUMNS:
        conn.execute(
            sa.text(
                "UPDATE board_cards SET column_code = :back "
                "WHERE board = :b AND column_code = :code"
            ),
            {"b": BOARD, "code": code, "back": back},
        )
        at = conn.execute(
            sa.text(
                "DELETE FROM board_columns WHERE board = :b AND code = :code "
                "RETURNING position"
            ),
            {"b": BOARD, "code": code},
        ).scalar()
        if at is not None:
            conn.execute(
                sa.text(
                    "UPDATE board_columns SET position = position - 1 "
                    "WHERE board = :b AND position > :at"
                ),
                {"b": BOARD, "at": at},
            )
