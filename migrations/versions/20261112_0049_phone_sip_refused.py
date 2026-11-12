"""`phone_extensions.sip_refused_at`: when the exchange refused a number's
password to the browser phone, which stays stopped since.

Additive and idempotent: one nullable column.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE phone_extensions "
        "ADD COLUMN IF NOT EXISTS sip_refused_at timestamptz NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE phone_extensions DROP COLUMN IF EXISTS sip_refused_at")
