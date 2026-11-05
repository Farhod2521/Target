"""The expert table's chosen columns, beside the panel's chosen cards.

`metric_preferences.expert_chosen`: the metric keys the owner keeps on, in
their order; null is every column. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE metric_preferences ADD COLUMN IF NOT EXISTS expert_chosen jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE metric_preferences DROP COLUMN IF EXISTS expert_chosen")
