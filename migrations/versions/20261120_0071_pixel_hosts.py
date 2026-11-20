"""Pixels: the websites each one fired on this week.

Schema (additive): ``pixel_accounts.hosts``, read from Meta's pixel stats
by host with the events, so a site-lead launch can say when its pixel is
not on the ad's website. Empty until the next read; the downgrade drops it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0071"
down_revision: str | Sequence[str] | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE pixel_accounts "
        "ADD COLUMN IF NOT EXISTS hosts jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE pixel_accounts DROP COLUMN IF EXISTS hosts")
