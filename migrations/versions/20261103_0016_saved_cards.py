"""Rahmat autopay: a payer's card kept as Multicard's token.

`saved_cards` holds a row per binding page opened; at most one active card
per owner. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE = """
    CREATE TABLE IF NOT EXISTS saved_cards (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider varchar(32) NOT NULL DEFAULT 'multicard',
        session_id varchar(64) NOT NULL UNIQUE,
        status varchar(16) NOT NULL DEFAULT 'pending',
        token_encrypted bytea,
        token_fingerprint varchar(32) NOT NULL DEFAULT '',
        pan varchar(32) NOT NULL DEFAULT '',
        ps varchar(16) NOT NULL DEFAULT '',
        holder varchar(100) NOT NULL DEFAULT '',
        autopay boolean NOT NULL DEFAULT true,
        consented_at timestamptz NOT NULL,
        bound_at timestamptz,
        revoked_at timestamptz,
        charge_term timestamptz,
        charge_attempts smallint NOT NULL DEFAULT 0,
        last_charge_at timestamptz,
        last_charge_uuid varchar(64) NOT NULL DEFAULT '',
        last_charge_outcome varchar(16) NOT NULL DEFAULT '',
        last_charge_error varchar(300) NOT NULL DEFAULT ''
    )
"""
INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_saved_cards_owner_id ON saved_cards (owner_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_card_per_owner "
    "ON saved_cards (owner_id) WHERE status = 'active'",
    "CREATE INDEX IF NOT EXISTS saved_cards_status_autopay_idx "
    "ON saved_cards (status, autopay)",
)


def upgrade() -> None:
    op.execute(CREATE)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS saved_cards")
