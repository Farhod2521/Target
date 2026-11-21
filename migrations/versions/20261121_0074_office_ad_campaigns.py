"""The campaigns the office's advertising figures count, and nothing else.

Schema (additive): ``office_ad_campaigns`` - one row per campaign of the
office's ad account (``OFFICE_AD_ACCOUNT``) the superuser picked. Empty after
the migration: nothing is counted until campaigns are picked. The downgrade
drops the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0074"
down_revision: str | Sequence[str] | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS office_ad_campaigns ("
        "campaign_external_id varchar(128) PRIMARY KEY, "
        "picked_by_id uuid NULL REFERENCES users(id) ON DELETE SET NULL, "
        "created_at timestamptz NOT NULL DEFAULT now())"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS office_ad_campaigns")
