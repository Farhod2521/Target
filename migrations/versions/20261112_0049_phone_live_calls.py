"""Telephony's calls going on now: `phone_live_calls`.

A row from a call's first event to its last. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS phone_live_calls (
        id uuid PRIMARY KEY,
        connection_id uuid NOT NULL REFERENCES phone_connections (id) ON DELETE CASCADE,
        call_id varchar(64) NOT NULL,
        direction varchar(8) NOT NULL,
        number varchar(20) NOT NULL,
        extension varchar(16) NOT NULL DEFAULT '',
        state varchar(8) NOT NULL,
        started_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_phone_live_call "
    "ON phone_live_calls (connection_id, call_id)",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS phone_live_calls")
