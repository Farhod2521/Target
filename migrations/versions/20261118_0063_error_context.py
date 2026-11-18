"""What a fault was about: the launch or press, the step, what was sent and
what came back. The Developers read it beside the trace.

Additive and idempotent: the column is added if missing, empty for old rows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0063"
down_revision: str | Sequence[str] | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE error_events"
        " ADD COLUMN IF NOT EXISTS context jsonb NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE error_events DROP COLUMN IF EXISTS context")
