"""Whether the owner reads Reklama and the dashboard in Expert mode.

`users.expert_mode`: off for everybody until they switch it on. Additive and
idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS expert_mode boolean "
        "NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS expert_mode")
