"""Delivery stops, and the account's money standing a sync reads.

Idempotent: a database created from the baseline already has both, since
the baseline builds whatever the models hold.
"""

from collections.abc import Sequence

from alembic import op

from app.modules.ads.models import DeliveryStop

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ad_accounts "
        "ADD COLUMN IF NOT EXISTS standing varchar(24) NOT NULL DEFAULT '', "
        "ADD COLUMN IF NOT EXISTS balance_minor bigint NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS prepaid boolean NULL"
    )
    DeliveryStop.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    DeliveryStop.__table__.drop(bind=op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TABLE ad_accounts DROP COLUMN IF EXISTS standing, "
        "DROP COLUMN IF EXISTS balance_minor, DROP COLUMN IF EXISTS prepaid"
    )
