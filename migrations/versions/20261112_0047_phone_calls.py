"""Telephony's finished calls: `phone_calls`.

One row per call the exchange saved, by its `call_id`. `number` is the
other side as a client's phone is kept, so a card finds its calls by it.
Additive and idempotent: one new table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047"
down_revision: str | Sequence[str] | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS phone_calls (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        connection_id uuid NOT NULL REFERENCES phone_connections (id) ON DELETE CASCADE,
        call_id varchar(64) NOT NULL,
        direction varchar(8) NOT NULL,
        answered boolean NOT NULL,
        number varchar(20) NOT NULL,
        extension varchar(16) NOT NULL DEFAULT '',
        line varchar(20) NOT NULL DEFAULT '',
        user_id uuid NULL REFERENCES users (id) ON DELETE SET NULL,
        started_at timestamptz NOT NULL,
        duration_seconds integer NOT NULL DEFAULT 0,
        talk_seconds integer NOT NULL DEFAULT 0,
        recording_url text NOT NULL DEFAULT ''
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_phone_call ON phone_calls (connection_id, call_id)",
    "CREATE INDEX IF NOT EXISTS phone_calls_time_idx ON phone_calls (connection_id, started_at)",
    "CREATE INDEX IF NOT EXISTS phone_calls_number_idx ON phone_calls (number)",
    "CREATE INDEX IF NOT EXISTS ix_phone_calls_user_id ON phone_calls (user_id)",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS phone_calls")
