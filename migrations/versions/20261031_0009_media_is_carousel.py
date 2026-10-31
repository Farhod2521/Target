"""Whether an Instagram post is an album.

``is_carousel`` decides how a post reaches a lead advert. Additive and
idempotent: an existing post reads false until the next media sync marks it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE media_assets "
        "ADD COLUMN IF NOT EXISTS is_carousel boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE media_assets DROP COLUMN IF EXISTS is_carousel")
