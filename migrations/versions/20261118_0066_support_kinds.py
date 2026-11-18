"""The kinds of Support ticket each member takes first.

``board_support_kinds`` is new: a member with no row takes every kind, so
nothing changes until the Owner sets one. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0066"
down_revision: str | Sequence[str] | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS board_support_kinds (
            member_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            reason varchar(24) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            set_by_id uuid NULL REFERENCES users (id) ON DELETE SET NULL,
            PRIMARY KEY (member_id, reason)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_board_support_kinds_set_by_id"
        " ON board_support_kinds (set_by_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS board_support_kinds")
