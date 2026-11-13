"""The Sales discount runs on its own; «Chegirmasiz» is no longer reached.

The discount now starts by itself (a Start payment, or the manager's
«Gaplashildi») and a card whose discount ran out closes into Yopildi, so
nothing puts a card into «Chegirmasiz» any more. The column is hidden, but
only where it stands empty: cards the old rule left in it stay on the board
with their managers until they are worked off.

No card is moved and no row is deleted. The downgrade shows the column again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE board_columns SET is_visible = false, updated_at = now() "
            "WHERE board = 'sales' AND code = 'no_discount' AND NOT EXISTS ("
            "SELECT 1 FROM board_cards WHERE board_cards.board = 'sales' "
            "AND board_cards.column_code = 'no_discount' "
            "AND board_cards.closed_at IS NULL)"
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE board_columns SET is_visible = true, updated_at = now() "
            "WHERE board = 'sales' AND code = 'no_discount'"
        )
    )
