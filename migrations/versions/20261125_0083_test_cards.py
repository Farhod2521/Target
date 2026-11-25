"""Office «Testing»: cards the superuser binds for trial payments.

Schema (additive): ``test_cards``, a Multicard card token per binding made
from the office, kept apart from ``saved_cards`` so the account's own card
and autopay are never touched; ``test_payments.card_id`` names the test
card a payment was taken from (null: the account's card or the page). The
downgrade drops both.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083"
down_revision: str | Sequence[str] | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_cards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("pan", sa.String(32), nullable=False, server_default=""),
        sa.Column("ps", sa.String(16), nullable=False, server_default=""),
        sa.Column("holder", sa.String(100), nullable=False, server_default=""),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_test_cards_created_at", "test_cards", ["created_at"])
    op.create_index("ix_test_cards_actor_id", "test_cards", ["actor_id"])
    op.add_column(
        "test_payments",
        sa.Column(
            "card_id",
            sa.Uuid(),
            sa.ForeignKey("test_cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("test_payments", "card_id")
    op.drop_table("test_cards")
