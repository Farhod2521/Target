"""CRM manager seats: what a bill buys and what a plan charges for one.

Django billing 0027 and 0028. Idempotent, like 0002: a database copied from
the Django project already has every column.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE invoices "
        "ADD COLUMN IF NOT EXISTS seats smallint NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS seats_minor bigint NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS seats_from timestamptz NULL, "
        "ADD COLUMN IF NOT EXISTS seats_until timestamptz NULL, "
        "ADD COLUMN IF NOT EXISTS seats_days smallint NOT NULL DEFAULT 0"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS invoices_owner_i_60d826_idx "
        "ON invoices (owner_id, seats_until)"
    )
    op.execute(
        "ALTER TABLE plans "
        "ADD COLUMN IF NOT EXISTS crm_seat_price bigint NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS crm_free_seats smallint NOT NULL DEFAULT 1"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE plans DROP COLUMN IF EXISTS crm_seat_price, "
        "DROP COLUMN IF EXISTS crm_free_seats"
    )
    op.execute("DROP INDEX IF EXISTS invoices_owner_i_60d826_idx")
    op.execute(
        "ALTER TABLE invoices DROP COLUMN IF EXISTS seats, "
        "DROP COLUMN IF EXISTS seats_minor, DROP COLUMN IF EXISTS seats_from, "
        "DROP COLUMN IF EXISTS seats_until, DROP COLUMN IF EXISTS seats_days"
    )
