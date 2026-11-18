"""`tutorials`: Russian and English beside Uzbek. Every lesson written so far
keeps its columns, which are the Uzbek ones, so it reads as Uzbek and shows
in every language until another is written. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("title", "varchar(200)"),
    ("description", "text"),
    ("image", "varchar(255)"),
    ("video_url", "varchar(500)"),
    ("video_file", "varchar(255)"),
)
LANGUAGES = ("ru", "en")


def upgrade() -> None:
    for language in LANGUAGES:
        for name, kind in COLUMNS:
            op.execute(
                f"ALTER TABLE tutorials ADD COLUMN IF NOT EXISTS "
                f"{name}_{language} {kind} NOT NULL DEFAULT ''"
            )


def downgrade() -> None:
    for language in LANGUAGES:
        for name, _ in COLUMNS:
            op.execute(f"ALTER TABLE tutorials DROP COLUMN IF EXISTS {name}_{language}")
