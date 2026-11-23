"""A creative says whether people see a video.

Schema (additive): ``ad_creatives.is_video`` boolean, default false. Filled
for the rows already known to be videos - a ``video_data`` creative or one
with a video id. Boosted video posts and reels turn true on the next sync,
which now asks Meta for ``object_type`` and the creative's own ``video_id``.
The downgrade drops the column.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0076"
down_revision: str | Sequence[str] | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ad_creatives "
        "ADD COLUMN IF NOT EXISTS is_video boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "UPDATE ad_creatives SET is_video = true WHERE kind = 'video' OR video_id <> ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ad_creatives DROP COLUMN IF EXISTS is_video")
