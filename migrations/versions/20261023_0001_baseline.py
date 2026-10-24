"""Baseline: the schema the Django project left behind.

On the existing database run `alembic stamp 0001` - every table is already
there. On an empty database `alembic upgrade head` creates them all.
"""

from collections.abc import Sequence

from alembic import op

from app import models  # noqa: F401
from app.common.db import Base

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
