"""The half-hourly guard takes over what the morning message said.

- The morning's price rises and frequency levels are no longer written, so
  the ones still open are closed: nothing would ever close them again, and
  they would stay on the waiting list beside the guard's own lines.
- After a change, the same group is left alone for 24 hours, not 48. Only
  the owners still on the old default are moved; a number an owner chose is
  theirs.

Idempotent: a second run finds nothing open and no 48 left.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0058"
down_revision: str | Sequence[str] | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS: tuple[str, ...] = (
    "UPDATE agent_price_alerts SET closed_at = now(), updated_at = now() "
    "WHERE closed_at IS NULL",
    "UPDATE agent_frequency_alerts SET closed_at = now(), updated_at = now() "
    "WHERE closed_at IS NULL",
    "UPDATE agent_policies SET cooldown_hours = 24 WHERE cooldown_hours = 48",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Nothing to put back: which alerts were open, and whose 24 hours were
    the old default's, is not kept anywhere."""
