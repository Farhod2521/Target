"""Pixels: the websites each one fired on this week, and its events' quality.

Schema (additive), both read from Meta with the events and empty until the
next read; the downgrade drops them:

- ``pixel_accounts.hosts``: from the pixel stats by host, so a site-lead
  launch can say when its pixel is not on the ad's website;
- ``pixel_accounts.quality``: Meta's Dataset Quality answer per event (match
  quality 0-10, server coverage, dedupe by event id).
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
        "ADD COLUMN IF NOT EXISTS hosts jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "ADD COLUMN IF NOT EXISTS quality jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE pixel_accounts DROP COLUMN IF EXISTS hosts, "
        "DROP COLUMN IF EXISTS quality"
    )
