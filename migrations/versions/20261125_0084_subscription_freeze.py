"""A subscription the office froze.

Schema (additive): ``subscriptions.frozen_at``, ``frozen_until``,
``frozen_reason`` and ``frozen_by_id``. While ``frozen_at`` is set the
subscription serves nothing, and the time it stays frozen is added to
``expires_at`` when it is released. The downgrade drops the columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | Sequence[str] | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("frozen_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("frozen_reason", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "frozen_by_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="subscriptions_frozen_by_id_fkey",
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "subscriptions_frozen_until_idx",
        "subscriptions",
        ["frozen_until"],
        postgresql_where=sa.text("frozen_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("subscriptions_frozen_until_idx", table_name="subscriptions")
    op.drop_column("subscriptions", "frozen_by_id")
    op.drop_column("subscriptions", "frozen_reason")
    op.drop_column("subscriptions", "frozen_until")
    op.drop_column("subscriptions", "frozen_at")
