"""TZ 3: a pixel's custom conversions and their seven-day counts,
`pixel_accounts.conversions`. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE pixel_accounts "
        "ADD COLUMN IF NOT EXISTS conversions jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE pixel_accounts DROP COLUMN IF EXISTS conversions")
