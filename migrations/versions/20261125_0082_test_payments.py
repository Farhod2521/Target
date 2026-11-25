"""Office «Testing»: the superuser's own trial payments.

Schema (additive): ``test_payments``, one row per real payment the superuser
makes from the office to try a card (a dollar's worth, in so'm). It pays for
nothing. The downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0082"
down_revision: str | Sequence[str] | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("number", sa.String(32), nullable=False, unique=True),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("usd_cents", sa.BigInteger(), nullable=False),
        sa.Column("amount_uzs", sa.BigInteger(), nullable=False),
        sa.Column("rate", sa.String(32), nullable=False, server_default=""),
        sa.Column("rate_date", sa.String(16), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="created"),
        sa.Column("external_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("page_url", sa.String(512), nullable=False, server_default=""),
        sa.Column("card_pan", sa.String(32), nullable=False, server_default=""),
        sa.Column("card_ps", sa.String(16), nullable=False, server_default=""),
        sa.Column("detail", sa.String(255), nullable=False, server_default=""),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")
        ),
    )
    op.create_index("ix_test_payments_created_at", "test_payments", ["created_at"])
    op.create_index("ix_test_payments_actor_id", "test_payments", ["actor_id"])


def downgrade() -> None:
    op.drop_table("test_payments")
