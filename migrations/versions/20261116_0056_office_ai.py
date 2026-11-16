"""The office's assistant: `office_ai_threads`, `office_ai_messages`.

A person in the office asks about the product - sign-ups, payments, plans,
what waits - and the assistant answers from the office's own read-only
figures. A thread belongs to the one who wrote it. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0056"
down_revision: str | Sequence[str] | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS office_ai_threads (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        staff_id uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
        title varchar(120) NOT NULL DEFAULT '',
        last_message_at timestamptz NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_office_ai_threads_created_at ON office_ai_threads (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_office_ai_threads_staff_id ON office_ai_threads (staff_id)",
    "CREATE INDEX IF NOT EXISTS office_ai_thread_recent_idx ON office_ai_threads (staff_id, last_message_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS office_ai_messages (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        staff_id uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
        thread_id uuid NOT NULL REFERENCES office_ai_threads (id) ON DELETE CASCADE,
        author varchar(8) NOT NULL DEFAULT '',
        text text NOT NULL DEFAULT '',
        html text NOT NULL DEFAULT '',
        status varchar(16) NOT NULL DEFAULT 'done',
        masked_figures integer NOT NULL DEFAULT 0,
        meta jsonb NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_office_ai_messages_created_at ON office_ai_messages (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_office_ai_messages_staff_id ON office_ai_messages (staff_id)",
    "CREATE INDEX IF NOT EXISTS ix_office_ai_messages_thread_id ON office_ai_messages (thread_id)",
    "CREATE INDEX IF NOT EXISTS office_ai_message_thread_idx ON office_ai_messages (thread_id, created_at)",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS office_ai_messages")
    op.execute("DROP TABLE IF EXISTS office_ai_threads")
