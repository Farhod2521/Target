"""Website purchases on the daily figures, unique link clicks on the ranges.

`metrics_daily.purchases_site` / `purchase_value_site_minor`: Meta's
"Website purchases" and their value. `metrics_people_count.unique_link_clicks`:
people who clicked the link over a whole range, read beside reach. Additive,
constant defaults, idempotent. Older days fill in on the next history refill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE metrics_daily "
        "ADD COLUMN IF NOT EXISTS purchases_site bigint NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS purchase_value_site_minor bigint NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE metrics_people_count "
        "ADD COLUMN IF NOT EXISTS unique_link_clicks bigint NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE metrics_people_count DROP COLUMN IF EXISTS unique_link_clicks"
    )
    op.execute(
        "ALTER TABLE metrics_daily DROP COLUMN IF EXISTS purchases_site, "
        "DROP COLUMN IF EXISTS purchase_value_site_minor"
    )
