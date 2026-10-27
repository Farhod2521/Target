"""When Meta was told a CRM card's lead was qualified.

Django crm 0003. Idempotent: a database copied from the Django project
already has the column.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE crm_cards ADD COLUMN IF NOT EXISTS quality_sent_at timestamptz NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE crm_cards DROP COLUMN IF EXISTS quality_sent_at")
