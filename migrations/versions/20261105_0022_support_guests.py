"""The sign-in page's support chat: `support_guest_chats` and
`support_guest_messages`, for somebody not signed in. Words only; signing in
moves them into that account's own chat. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_CHATS = """
    CREATE TABLE IF NOT EXISTS support_guest_chats (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        token_hash varchar(64) NOT NULL UNIQUE,
        name varchar(120) NOT NULL DEFAULT '',
        phone varchar(32) NOT NULL DEFAULT '',
        email varchar(254) NOT NULL DEFAULT '',
        last_message_at timestamptz,
        last_guest_at timestamptz,
        last_office_at timestamptz,
        guest_read_at timestamptz,
        office_read_at timestamptz,
        settled_at timestamptz,
        claimed_by_id uuid REFERENCES users(id) ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED,
        claimed_at timestamptz
    )
"""
CREATE_MESSAGES = """
    CREATE TABLE IF NOT EXISTS support_guest_messages (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        chat_id uuid NOT NULL REFERENCES support_guest_chats(id) ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED,
        from_guest boolean NOT NULL DEFAULT true,
        sender_id uuid REFERENCES users(id) ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED,
        body text NOT NULL DEFAULT ''
    )
"""
INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_support_guest_chats_created_at "
    "ON support_guest_chats (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_support_guest_chats_email "
    "ON support_guest_chats (email)",
    "CREATE INDEX IF NOT EXISTS ix_support_guest_chats_claimed_by_id "
    "ON support_guest_chats (claimed_by_id)",
    "CREATE INDEX IF NOT EXISTS support_guest_queue_idx "
    "ON support_guest_chats (last_message_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_support_guest_messages_created_at "
    "ON support_guest_messages (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_support_guest_messages_sender_id "
    "ON support_guest_messages (sender_id)",
    "CREATE INDEX IF NOT EXISTS support_guest_msg_thread_idx "
    "ON support_guest_messages (chat_id, created_at)",
)


def upgrade() -> None:
    op.execute(CREATE_CHATS)
    op.execute(CREATE_MESSAGES)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS support_guest_messages")
    op.execute("DROP TABLE IF EXISTS support_guest_chats")
