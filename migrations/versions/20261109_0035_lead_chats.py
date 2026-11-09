"""Leads posted to a Telegram group or channel: `lead_chats`, and which
page and ad account pair goes to which (`lead_chat_pairs`). Additive and
idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS lead_chats (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        chat_id varchar(32) NOT NULL,
        kind varchar(16) NOT NULL,
        title varchar(255) NOT NULL DEFAULT '',
        status varchar(16) NOT NULL,
        broken_reason varchar(16) NOT NULL DEFAULT '',
        linked_at timestamptz NOT NULL,
        broken_at timestamptz,
        checked_at timestamptz,
        last_error varchar(255) NOT NULL DEFAULT '',
        CONSTRAINT uniq_lead_chat_per_owner UNIQUE (owner_id, chat_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_lead_chats_created_at ON lead_chats (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_lead_chats_owner_id ON lead_chats (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_lead_chats_chat_id ON lead_chats (chat_id)",
    """
    CREATE TABLE IF NOT EXISTS lead_chat_pairs (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        lead_chat_id uuid NOT NULL REFERENCES lead_chats(id) ON DELETE CASCADE,
        page_id uuid NOT NULL REFERENCES page_accounts(id) ON DELETE CASCADE,
        ad_account_id uuid NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
        linked_at timestamptz NOT NULL,
        CONSTRAINT uniq_lead_chat_pair UNIQUE (page_id, ad_account_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_lead_chat_pairs_owner_id ON lead_chat_pairs (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_lead_chat_pairs_lead_chat_id "
    "ON lead_chat_pairs (lead_chat_id)",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lead_chat_pairs")
    op.execute("DROP TABLE IF EXISTS lead_chats")
