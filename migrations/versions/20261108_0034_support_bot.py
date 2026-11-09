"""The support bot: `support_bot_chats`, and where a support message came
from (`support_messages.source`), which copy of a reply a relay is
(`support_relays.part`), and a guest chat's channel
(`support_guest_chats.channel`). Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = """
CREATE TABLE IF NOT EXISTS support_bot_chats (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    chat_id varchar(32) NOT NULL UNIQUE,
    username varchar(64) NOT NULL DEFAULT '',
    name varchar(120) NOT NULL DEFAULT '',
    owner_id uuid REFERENCES users(id) ON DELETE CASCADE,
    guest_chat_id uuid REFERENCES support_guest_chats(id) ON DELETE SET NULL,
    is_active boolean NOT NULL DEFAULT true,
    linked_at timestamptz,
    last_error varchar(32) NOT NULL DEFAULT '',
    last_error_at timestamptz
)
"""
STATEMENTS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_support_bot_chat_per_owner "
    "ON support_bot_chats (owner_id) WHERE is_active = true AND owner_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_support_bot_chats_created_at "
    "ON support_bot_chats (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_support_bot_chats_owner_id "
    "ON support_bot_chats (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_support_bot_chats_guest_chat_id "
    "ON support_bot_chats (guest_chat_id)",
    "ALTER TABLE support_messages "
    "ADD COLUMN IF NOT EXISTS source varchar(16) NOT NULL DEFAULT 'site'",
    "ALTER TABLE support_relays "
    "ADD COLUMN IF NOT EXISTS part varchar(8) NOT NULL DEFAULT ''",
    "ALTER TABLE support_guest_chats "
    "ADD COLUMN IF NOT EXISTS channel varchar(16) NOT NULL DEFAULT 'site'",
)


def upgrade() -> None:
    op.execute(TABLE)
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE support_guest_chats DROP COLUMN IF EXISTS channel")
    op.execute("ALTER TABLE support_relays DROP COLUMN IF EXISTS part")
    op.execute("ALTER TABLE support_messages DROP COLUMN IF EXISTS source")
    op.execute("DROP TABLE IF EXISTS support_bot_chats")
