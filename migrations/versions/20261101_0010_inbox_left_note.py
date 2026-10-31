"""What a line said when its owner left it as it is.

The record shows left lines by this note, since the key alone is a digest.
Additive and idempotent: an existing row reads empty.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE inbox_seen "
        "ADD COLUMN IF NOT EXISTS note varchar(255) NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE inbox_seen DROP COLUMN IF EXISTS note")
