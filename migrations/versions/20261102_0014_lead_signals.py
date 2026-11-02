"""One queue for everything told to the provider about a lead.

`lead_signals` holds a row per lead and stage. What Django already sent moves in
as `sent`, so nothing goes twice. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE = """
    CREATE TABLE IF NOT EXISTS lead_signals (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users(id),
        lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        ad_account_id uuid NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
        stage varchar(16) NOT NULL,
        source varchar(16) NOT NULL,
        occurred_at timestamptz NOT NULL,
        value_minor bigint,
        currency varchar(3) NOT NULL DEFAULT '',
        status varchar(16) NOT NULL DEFAULT 'pending',
        sent_at timestamptz,
        attempts smallint NOT NULL DEFAULT 0,
        dataset_id varchar(128) NOT NULL DEFAULT '',
        trace_id varchar(128) NOT NULL DEFAULT '',
        last_error varchar(500) NOT NULL DEFAULT '',
        CONSTRAINT uniq_signal_per_stage UNIQUE (lead_id, stage)
    )
"""
INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_lead_signals_created_at ON lead_signals (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_lead_signals_owner_id ON lead_signals (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_lead_signals_lead_id ON lead_signals (lead_id)",
    "CREATE INDEX IF NOT EXISTS ix_lead_signals_ad_account_id "
    "ON lead_signals (ad_account_id)",
    "CREATE INDEX IF NOT EXISTS lead_signals_owner_status_idx "
    "ON lead_signals (owner_id, status)",
    "CREATE INDEX IF NOT EXISTS lead_signals_status_occurred_idx "
    "ON lead_signals (status, occurred_at)",
)
SENT_BY_DJANGO = """
    INSERT INTO lead_signals (
        id, created_at, updated_at, owner_id, lead_id, ad_account_id, stage,
        source, occurred_at, status, sent_at, currency, attempts, dataset_id,
        trace_id, last_error
    )
    SELECT gen_random_uuid(), now(), now(), owner_id, lead_id, ad_account_id,
           'qualified', 'internal', COALESCE(qualified_at, quality_sent_at),
           'sent', quality_sent_at, '', 1, '', '', ''
    FROM crm_cards
    WHERE quality_sent_at IS NOT NULL AND ad_account_id IS NOT NULL
    ON CONFLICT (lead_id, stage) DO NOTHING
"""


def upgrade() -> None:
    op.execute(CREATE)
    for statement in INDEXES:
        op.execute(statement)
    op.execute(SENT_BY_DJANGO)


def downgrade() -> None:
    """A record of what Meta was told; nothing is taken back."""
