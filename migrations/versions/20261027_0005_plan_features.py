"""A tier card's lines, in three languages.

Django billing 0029. Idempotent: a database copied from the Django project
already has the table.
"""

from collections.abc import Sequence

from alembic import op

from app.modules.billing.models import PlanFeature

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    PlanFeature.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    PlanFeature.__table__.drop(bind=op.get_bind(), checkfirst=True)
