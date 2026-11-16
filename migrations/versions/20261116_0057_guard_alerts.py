"""The half-hourly guard's findings: `agent_guard_alerts`.

One open row a group (or advert) and kind: a price three, four, five times
the usual one, money gone with nothing back, a page that does not open, a
weak advert, a fallen click rate. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0057"
down_revision: str | Sequence[str] | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = """
CREATE TABLE IF NOT EXISTS agent_guard_alerts (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    provider varchar(32) NOT NULL DEFAULT '',
    ad_account_id uuid NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
    level varchar(16) NOT NULL DEFAULT 'adset',
    external_id varchar(128) NOT NULL DEFAULT '',
    adset_external_id varchar(128) NOT NULL DEFAULT '',
    campaign_external_id varchar(128) NOT NULL DEFAULT '',
    name text NOT NULL DEFAULT '',
    kind varchar(16) NOT NULL DEFAULT '',
    action varchar(8) NOT NULL DEFAULT 'warn',
    advice varchar(16) NOT NULL DEFAULT '',
    step integer NOT NULL DEFAULT 1,
    said_step integer NOT NULL DEFAULT 0,
    times integer NOT NULL DEFAULT 0,
    result_kind varchar(32) NOT NULL DEFAULT '',
    currency varchar(3) NOT NULL DEFAULT '',
    figures jsonb NOT NULL DEFAULT '{}'::jsonb,
    baseline jsonb NOT NULL DEFAULT '{}'::jsonb,
    action_log_id uuid,
    telegram_sent_at timestamptz,
    telegram_message_id bigint,
    answer varchar(16) NOT NULL DEFAULT '',
    answered_at timestamptz,
    closed_at timestamptz
)
"""
INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_open_guard_alert "
    "ON agent_guard_alerts (owner_id, provider, external_id, kind) "
    "WHERE closed_at IS NULL",
    "CREATE INDEX IF NOT EXISTS agent_guard_owner_open "
    "ON agent_guard_alerts (owner_id, closed_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_guard_alerts_created_at "
    "ON agent_guard_alerts (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_guard_alerts_owner_id "
    "ON agent_guard_alerts (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_guard_alerts_ad_account_id "
    "ON agent_guard_alerts (ad_account_id)",
)


def upgrade() -> None:
    op.execute(TABLE)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_guard_alerts")
