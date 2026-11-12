"""`metrics_daily.optimization_goal_raw`: what a row's ad set was bought for.

The mirror forgets a campaign Meta no longer lists; its figures stay, and
until now nothing on them said what the money bought, so a deleted traffic
campaign's spend was drawn as leads. The nightly read fills it for the last
fortnight; `python -m app.modules.metrics.refill --apply` for the ninety
days Meta still answers.

A constant default: PostgreSQL adds the column without rewriting the table.
Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044"
down_revision: str | Sequence[str] | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE metrics_daily "
        "ADD COLUMN IF NOT EXISTS optimization_goal_raw varchar(64) NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE metrics_daily DROP COLUMN IF EXISTS optimization_goal_raw")
