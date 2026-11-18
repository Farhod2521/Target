"""The kinds of Support ticket each member takes first, and the staff bot's
mark on a ticket's line.

``board_support_kinds`` is new: a member with no row takes every kind, so
nothing changes until the Owner sets one. ``board_card_events.noticed_at``
says the ticket's person was told of the line; ``created_at`` gets an index
for the daily report and the notices. Additive and idempotent.
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

    op.execute(
        "ALTER TABLE board_card_events"
        " ADD COLUMN IF NOT EXISTS noticed_at timestamptz NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS board_card_events_created_idx"
        " ON board_card_events (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS board_card_events_created_idx")
    op.execute("ALTER TABLE board_card_events DROP COLUMN IF EXISTS noticed_at")
    op.execute("DROP TABLE IF EXISTS board_support_kinds")
