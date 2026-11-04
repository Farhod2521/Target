"""The payments group's bot is gone, and with it `invoices.receipt_sent_at`.

Undoes 0015's column and index. Idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS invoices_receipt_owed")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS receipt_sent_at")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS receipt_sent_at timestamptz"
    )
    op.execute(
        "UPDATE invoices SET receipt_sent_at = COALESCE(paid_at, now()) "
        "WHERE receipt_sent_at IS NULL AND status IN ('paid', 'refunded')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS invoices_receipt_owed "
        "ON invoices (paid_at) WHERE receipt_sent_at IS NULL AND status = 'paid'"
    )
