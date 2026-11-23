"""Boards: the buttons each column's cards show, kept by the superuser.

Schema (additive): ``board_buttons``: one button of one column: a button of
the code («Gaplashildi», «Hal qilindi», …) with, where the superuser set
them, its own words and column, or a button of the superuser's own (``go``)
that only moves the card.

Rows: every column's buttons exactly as the code gave them until now, so no
card shows a different button after the deploy. The queues (Ishlanmagan,
Support's Yangi) and the columns that close a card are not in the table:
their buttons stay the code's.

The downgrade drops the table; the code's own buttons are what is left.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | Sequence[str] | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (board, column, button, place), as the code's tables had them.
SEEDS = (
    ("sales", "new_lead", "contacted", 1),
    ("sales", "new_lead", "no_contact", 2),
    ("sales", "new_lead", "callback", 3),
    ("sales", "new_lead", "close", 4),
    ("sales", "no_contact", "contacted", 1),
    ("sales", "no_contact", "no_contact", 2),
    ("sales", "no_contact", "callback", 3),
    ("sales", "no_contact", "close", 4),
    ("sales", "contacted", "callback", 1),
    ("sales", "contacted", "needs_support", 2),
    ("sales", "contacted", "close", 3),
    ("sales", "callback", "contacted", 1),
    ("sales", "callback", "no_contact", 2),
    ("sales", "callback", "callback", 3),
    ("sales", "callback", "needs_support", 4),
    ("sales", "callback", "close", 5),
    ("sales", "discount_20", "contacted", 1),
    ("sales", "discount_20", "no_contact", 2),
    ("sales", "discount_20", "callback", 3),
    ("sales", "discount_20", "needs_support", 4),
    ("sales", "discount_20", "close", 5),
    ("sales", "discount_10", "contacted", 1),
    ("sales", "discount_10", "no_contact", 2),
    ("sales", "discount_10", "callback", 3),
    ("sales", "discount_10", "needs_support", 4),
    ("sales", "discount_10", "close", 5),
    ("sales", "no_discount", "callback", 1),
    ("sales", "no_discount", "needs_support", 2),
    ("sales", "no_discount", "close", 3),
    ("sales", "awaiting", "callback", 1),
    ("sales", "awaiting", "needs_support", 2),
    ("sales", "awaiting", "close", 3),
    ("support", "in_progress", "wait", 1),
    ("support", "in_progress", "unreachable", 2),
    ("support", "in_progress", "to_developer", 3),
    ("support", "in_progress", "resolve", 4),
    ("support", "in_progress", "release", 5),
    ("support", "waiting", "start", 1),
    ("support", "waiting", "unreachable", 2),
    ("support", "waiting", "resolve", 3),
    ("support", "waiting", "release", 4),
    ("support", "unreachable", "start", 1),
    ("support", "unreachable", "release", 2),
    ("support", "developer", "start", 1),
    ("support", "developer", "resolve", 2),
    ("renewal", "ending", "contacted", 1),
    ("renewal", "ending", "no_contact", 2),
    ("renewal", "ending", "callback", 3),
    ("renewal", "ending", "decline", 4),
    ("renewal", "ended", "contacted", 1),
    ("renewal", "ended", "no_contact", 2),
    ("renewal", "ended", "callback", 3),
    ("renewal", "ended", "decline", 4),
    ("renewal", "no_contact", "contacted", 1),
    ("renewal", "no_contact", "no_contact", 2),
    ("renewal", "no_contact", "callback", 3),
    ("renewal", "no_contact", "decline", 4),
    ("renewal", "contacted", "callback", 1),
    ("renewal", "contacted", "will_pay", 2),
    ("renewal", "contacted", "decline", 3),
    ("renewal", "callback", "contacted", 1),
    ("renewal", "callback", "no_contact", 2),
    ("renewal", "callback", "callback", 3),
    ("renewal", "callback", "will_pay", 4),
    ("renewal", "callback", "decline", 5),
    ("renewal", "awaiting", "callback", 1),
    ("renewal", "awaiting", "decline", 2),
)


def upgrade() -> None:
    op.create_table(
        "board_buttons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("board", sa.String(16), nullable=False),
        sa.Column("column_code", sa.String(24), nullable=False),
        sa.Column("code", sa.String(24), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("label", sa.String(40), nullable=False, server_default=""),
        sa.Column("to_column", sa.String(24), nullable=False, server_default=""),
        sa.Column("due", sa.String(16), nullable=False, server_default=""),
        sa.Column(
            "note_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "uniq_board_button_code",
        "board_buttons",
        ["board", "column_code", "code"],
        unique=True,
    )
    op.create_index(
        "board_buttons_order_idx", "board_buttons", ["board", "column_code", "position"]
    )
    op.create_index(
        "ix_board_buttons_created_by_id", "board_buttons", ["created_by_id"]
    )
    insert = sa.text(
        "INSERT INTO board_buttons (id, created_at, updated_at, board, column_code, "
        "code, action, position, is_default) VALUES (gen_random_uuid(), now(), "
        "now(), :board, :column_code, :code, :code, :position, true)"
    )
    bind = op.get_bind()
    for board, column_code, code, position in SEEDS:
        bind.execute(
            insert,
            {
                "board": board,
                "column_code": column_code,
                "code": code,
                "position": position,
            },
        )


def downgrade() -> None:
    op.drop_table("board_buttons")
