"""board_cards.chat_taken_at

A person in Support answers the client in the one chat («Men javob
beraman»): from that moment the assistant does not answer them. The person
is the Support card's own. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061"
down_revision: str | Sequence[str] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE board_cards ADD COLUMN IF NOT EXISTS chat_taken_at timestamptz"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE board_cards DROP COLUMN IF EXISTS chat_taken_at")
