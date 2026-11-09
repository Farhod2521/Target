"""The pictures step's tiles: a library video's length and whether an
Instagram post is a feed post or a reel, `media_assets.duration_seconds` and
`media_assets.product`. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE media_assets "
        "ADD COLUMN IF NOT EXISTS duration_seconds double precision NULL"
    )
    op.execute(
        "ALTER TABLE media_assets "
        "ADD COLUMN IF NOT EXISTS product varchar(16) NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE media_assets DROP COLUMN IF EXISTS product")
    op.execute("ALTER TABLE media_assets DROP COLUMN IF EXISTS duration_seconds")
