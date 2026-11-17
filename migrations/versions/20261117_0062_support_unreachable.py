"""Support's «Bog'lanib bo'lmadi»: a column, its reasons, the card's reason.

No way to reach a client: Support moves the ticket to «Bog'lanib bo'lmadi»
(after Mijoz kutilmoqda) with a reason from a list the Owner and the
superuser keep. Two reasons to start with: a wrong number and no answer on
Telegram.

Additive and idempotent: the table and the card's column are created if
missing, the two reasons only into an empty table, and the board column
only where the board was seeded and lacks it.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | Sequence[str] | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BOARD = "support"
CODE = "unreachable"
FIRST_REASONS = ("Telefon raqam xato", "Telegramdan bog'lanib bo'lmadi")


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(
        "CREATE TABLE IF NOT EXISTS board_contact_reasons ("
        " id uuid PRIMARY KEY,"
        " created_at timestamptz NOT NULL,"
        " updated_at timestamptz NOT NULL,"
        " name varchar(80) NOT NULL,"
        " position integer NOT NULL DEFAULT 0,"
        " is_archived boolean NOT NULL DEFAULT false,"
        " created_by_id uuid REFERENCES users(id) ON DELETE SET NULL)"
    )
    if not conn.execute(sa.text("SELECT 1 FROM board_contact_reasons LIMIT 1")).first():
        for position, name in enumerate(FIRST_REASONS, start=1):
            conn.execute(
                sa.text(
                    "INSERT INTO board_contact_reasons (id, created_at, updated_at,"
                    " name, position, is_archived) VALUES"
                    " (:id, now(), now(), :name, :position, false)"
                ),
                {"id": uuid.uuid4(), "name": name, "position": position},
            )
    op.execute(
        "ALTER TABLE board_cards ADD COLUMN IF NOT EXISTS unreachable_reason_id uuid"
        " REFERENCES board_contact_reasons(id) ON DELETE SET NULL"
    )
    rows = dict(
        conn.execute(
            sa.text("SELECT code, position FROM board_columns WHERE board = :b"),
            {"b": BOARD},
        ).all()
    )
    # No rows: the board was never seeded here, and the first read seeds it whole.
    if not rows or CODE in rows:
        return
    at = rows.get("waiting", max(rows.values()))
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
            "(:id, now(), now(), :b, :code, :name, :position, 'manual', false, true)"
        ),
        {
            "id": uuid.uuid4(),
            "b": BOARD,
            "code": CODE,
            "name": "Bog'lanib bo'lmadi",
            "position": at + 1,
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Its tickets step back to Mijoz kutilmoqda.
    conn.execute(
        sa.text(
            "UPDATE board_cards SET column_code = 'waiting' "
            "WHERE board = :b AND column_code = :code"
        ),
        {"b": BOARD, "code": CODE},
    )
    at = conn.execute(
        sa.text(
            "DELETE FROM board_columns WHERE board = :b AND code = :code "
            "RETURNING position"
        ),
        {"b": BOARD, "code": CODE},
    ).scalar()
    if at is not None:
        conn.execute(
            sa.text(
                "UPDATE board_columns SET position = position - 1 "
                "WHERE board = :b AND position > :at"
            ),
            {"b": BOARD, "at": at},
        )
    op.execute("ALTER TABLE board_cards DROP COLUMN IF EXISTS unreachable_reason_id")
    op.execute("DROP TABLE IF EXISTS board_contact_reasons")
