"""The Google Ads manager an account is reached through, on `ad_accounts`.
Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ad_accounts ADD COLUMN IF NOT EXISTS "
        "login_customer_id varchar(16) NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS login_customer_id")
