"""Rassilka: `broadcasts`, the bot's `broadcast_deliveries`, the site's
`broadcast_seen`, and the reader's `telegram_chats.notify_news` switch, on
for every chat. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS broadcasts (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        title varchar(120) NOT NULL DEFAULT '',
        body text NOT NULL DEFAULT '',
        image varchar(255) NOT NULL DEFAULT '',
        to_bot boolean NOT NULL DEFAULT false,
        to_channel boolean NOT NULL DEFAULT false,
        to_site boolean NOT NULL DEFAULT false,
        status varchar(16) NOT NULL DEFAULT 'draft',
        started_at timestamptz,
        finished_at timestamptz,
        photo_id varchar(255) NOT NULL DEFAULT '',
        channel_message_id bigint NOT NULL DEFAULT 0,
        channel_error varchar(255) NOT NULL DEFAULT '',
        created_by_id uuid REFERENCES users(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS broadcast_deliveries (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        broadcast_id uuid NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        chat_id varchar(32) NOT NULL DEFAULT '',
        status varchar(16) NOT NULL DEFAULT 'pending',
        message_id bigint NOT NULL DEFAULT 0,
        error varchar(255) NOT NULL DEFAULT '',
        CONSTRAINT uniq_broadcast_delivery_chat UNIQUE (broadcast_id, chat_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS broadcast_seen (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        seen_at timestamptz NOT NULL
    )
    """,
)
INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_broadcasts_created_at ON broadcasts (created_at)",
    "CREATE INDEX IF NOT EXISTS broadcasts_site_idx "
    "ON broadcasts (to_site, started_at)",
    "CREATE INDEX IF NOT EXISTS broadcast_deliveries_status_idx "
    "ON broadcast_deliveries (broadcast_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_broadcast_deliveries_owner_id "
    "ON broadcast_deliveries (owner_id)",
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE telegram_chats "
        "ADD COLUMN IF NOT EXISTS notify_news boolean NOT NULL DEFAULT true"
    )
    for statement in (*TABLES, *INDEXES):
        op.execute(statement)


def downgrade() -> None:
    for table in ("broadcast_seen", "broadcast_deliveries", "broadcasts"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("ALTER TABLE telegram_chats DROP COLUMN IF EXISTS notify_news")
