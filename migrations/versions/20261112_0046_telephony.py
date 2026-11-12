"""Telephony: `phone_connections`, `phone_extensions`, `phone_hook_events`.

A UTeL exchange tied to the office (`owner_id` empty; one such row), its
internal numbers with the person who answers each, and every event the
exchange sends, kept as it came. Additive and idempotent: only new tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS phone_connections (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NULL REFERENCES users (id) ON DELETE CASCADE,
        provider varchar(16) NOT NULL,
        tenant varchar(40) NOT NULL,
        api_email varchar(254) NOT NULL,
        api_token bytea NOT NULL,
        hook_key varchar(64) NOT NULL,
        hook_set_at timestamptz NULL,
        synced_at timestamptz NULL,
        last_error text NOT NULL DEFAULT '',
        connected_by_id uuid NULL REFERENCES users (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_phone_connections_owner_id ON phone_connections (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_phone_connections_connected_by_id "
    "ON phone_connections (connected_by_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_phone_connection_office "
    "ON phone_connections (provider) WHERE owner_id IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_phone_connection_hook_key "
    "ON phone_connections (hook_key)",
    """
    CREATE TABLE IF NOT EXISTS phone_extensions (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        connection_id uuid NOT NULL REFERENCES phone_connections (id) ON DELETE CASCADE,
        number varchar(16) NOT NULL,
        title varchar(60) NOT NULL DEFAULT '',
        sip_password bytea NOT NULL,
        user_id uuid NULL REFERENCES users (id) ON DELETE SET NULL,
        softphone boolean NOT NULL DEFAULT true,
        is_gone boolean NOT NULL DEFAULT false
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_phone_extensions_user_id ON phone_extensions (user_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_phone_extension_number "
    "ON phone_extensions (connection_id, number)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_phone_extension_user "
    "ON phone_extensions (connection_id, user_id) WHERE user_id IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS phone_hook_events (
        id uuid PRIMARY KEY,
        received_at timestamptz NOT NULL,
        connection_id uuid NOT NULL REFERENCES phone_connections (id) ON DELETE CASCADE,
        name varchar(40) NOT NULL DEFAULT '',
        call_id varchar(64) NOT NULL DEFAULT '',
        payload jsonb NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS phone_hook_events_time_idx "
    "ON phone_hook_events (connection_id, received_at)",
    "CREATE INDEX IF NOT EXISTS phone_hook_events_call_idx "
    "ON phone_hook_events (connection_id, call_id)",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS phone_hook_events")
    op.execute("DROP TABLE IF EXISTS phone_extensions")
    op.execute("DROP TABLE IF EXISTS phone_connections")
