"""A bill the super admin took off the books stays in the database, archived.

`invoices`: when, by whom and why. Empty on every bill written so far.
Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS archived_at timestamptz")
    op.execute(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS archived_by_id uuid "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE invoices "
        "ADD COLUMN IF NOT EXISTS archive_reason text NOT NULL DEFAULT ''"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS invoices_archived_by_id "
        "ON invoices (archived_by_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS invoices_archived_at_live "
        "ON invoices (archived_at) WHERE archived_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS invoices_archived_at_live")
    op.execute("DROP INDEX IF EXISTS invoices_archived_by_id")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS archive_reason")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS archived_by_id")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS archived_at")
