"""When the connected login stopped reaching an ad account: `ad_accounts.reach_lost_at`.

Set when Meta answers that this login cannot reach the account (another
Facebook profile was connected, or the role was taken away); cleared the next
time the login lists it again. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ad_accounts ADD COLUMN IF NOT EXISTS reach_lost_at timestamptz NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS reach_lost_at")
