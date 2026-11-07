"""TZ 1: a group whose result costs three times its usual price,
`agent_price_alerts`. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = """
CREATE TABLE IF NOT EXISTS agent_price_alerts (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    provider varchar(32) NOT NULL DEFAULT '',
    ad_account_id uuid NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
    adset_external_id varchar(128) NOT NULL DEFAULT '',
    ad_external_id varchar(128) NOT NULL DEFAULT '',
    name text NOT NULL DEFAULT '',
    result_kind varchar(160) NOT NULL DEFAULT '',
    currency varchar(3) NOT NULL DEFAULT '',
    spend_minor bigint NOT NULL DEFAULT 0,
    results integer NOT NULL DEFAULT 0,
    cost_minor bigint,
    cost_usual_minor bigint NOT NULL,
    times integer NOT NULL DEFAULT 0,
    baseline_source varchar(16) NOT NULL DEFAULT '',
    baseline_adverts integer NOT NULL DEFAULT 0,
    causes jsonb NOT NULL DEFAULT '[]'::jsonb,
    telegram_sent_at timestamptz,
    telegram_message_id bigint,
    answer varchar(16) NOT NULL DEFAULT '',
    answered_at timestamptz,
    hidden_until timestamptz,
    cost_after_7d_minor bigint,
    closed_at timestamptz
)
"""
INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_open_price_alert "
    "ON agent_price_alerts (owner_id, provider, adset_external_id) "
    "WHERE closed_at IS NULL",
    "CREATE INDEX IF NOT EXISTS agent_price_owner_open "
    "ON agent_price_alerts (owner_id, closed_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_price_alerts_created_at "
    "ON agent_price_alerts (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_price_alerts_owner_id "
    "ON agent_price_alerts (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_price_alerts_ad_account_id "
    "ON agent_price_alerts (ad_account_id)",
)


def upgrade() -> None:
    op.execute(TABLE)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_price_alerts")
