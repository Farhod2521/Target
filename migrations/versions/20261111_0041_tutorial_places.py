"""`tutorials.places`: the cabinet screens that show a lesson beside their
work. Every lesson written so far has none, so it stays in the Darsliklar
section only. Additive and idempotent.

Comes after 0040 (surveys), which another branch adds; merge that one first.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0041"
down_revision: str | Sequence[str] | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tutorials "
        "ADD COLUMN IF NOT EXISTS places varchar(32)[] NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tutorials DROP COLUMN IF EXISTS places")
