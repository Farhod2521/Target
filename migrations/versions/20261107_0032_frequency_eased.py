"""TZ 6.2: a required frequency level whose message went when the frequency
fell under 3.00, `agent_frequency_alerts.eased_at`. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_frequency_alerts "
        "ADD COLUMN IF NOT EXISTS eased_at timestamptz NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_frequency_alerts DROP COLUMN IF EXISTS eased_at")
