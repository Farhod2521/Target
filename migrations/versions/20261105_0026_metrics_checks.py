"""The nightly check against Ads Manager: `metrics_checks`, one row per
account per closed day, our stored sums beside Meta's own account total.
Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE = """
    CREATE TABLE IF NOT EXISTS metrics_checks (
        id bigserial PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED,
        ad_account_id uuid NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED,
        day date NOT NULL,
        ours jsonb NOT NULL DEFAULT '{}'::jsonb,
        theirs jsonb NOT NULL DEFAULT '{}'::jsonb,
        differs boolean NOT NULL DEFAULT false,
        checked_at timestamptz NOT NULL,
        CONSTRAINT uniq_metrics_check_per_day UNIQUE (ad_account_id, day)
    )
"""
INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_metrics_checks_owner_id ON metrics_checks (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_metrics_checks_ad_account_id "
    "ON metrics_checks (ad_account_id)",
    "CREATE INDEX IF NOT EXISTS ix_metrics_checks_differs ON metrics_checks (differs)",
)


def upgrade() -> None:
    op.execute(CREATE)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS metrics_checks")
