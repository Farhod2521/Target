"""Boards: the lists of reasons the superuser keeps.

Schema (additive): ``board_reasons``: one reason of one list (why a Sales
card is closed, why a client does not renew, why a call did not reach them,
why a card is moved by hand), with the code cards keep.

Rows: the reasons that were fixed in the code until now, under the same
codes, so every closed card and every report reads as before: five for
Sotuv «Yopish», seven for Uzaytirish «Rad etdi». The «Bog'lanib bo'lmadi»
and «Ko'chirish» lists start empty, which asks nothing new of anybody.

The downgrade drops the table; cards keep their codes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | Sequence[str] | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (board, purpose, code, name, note_required), in the lists' first order.
SEEDS = (
    ("sales", "close", "expensive", "Qimmat", False),
    ("sales", "close", "not_needed", "Kerak emas", False),
    ("sales", "close", "no_answer", "Javob bermaydi", False),
    ("sales", "close", "wrong_number", "Raqam noto'g'ri", False),
    ("sales", "close", "other", "Boshqa", True),
    ("renewal", "decline", "expensive", "Qimmat", False),
    ("renewal", "decline", "no_result", "Natija bo'lmadi", False),
    ("renewal", "decline", "meta_problem", "Meta muammosi", False),
    ("renewal", "decline", "business_stopped", "Biznes to'xtadi", False),
    ("renewal", "decline", "switched", "Boshqa tizimga o'tdi", False),
    ("renewal", "decline", "no_answer", "Javob bermadi", False),
    ("renewal", "decline", "other", "Boshqa", True),
)


def upgrade() -> None:
    op.create_table(
        "board_reasons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("board", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("code", sa.String(24), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "note_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_archived", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
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
        "uniq_board_reason_code",
        "board_reasons",
        ["board", "purpose", "code"],
        unique=True,
    )
    op.create_index(
        "board_reasons_order_idx", "board_reasons", ["board", "purpose", "position"]
    )
    op.create_index(
        "ix_board_reasons_created_by_id", "board_reasons", ["created_by_id"]
    )
    insert = sa.text(
        "INSERT INTO board_reasons (id, created_at, updated_at, board, purpose, "
        "code, name, position, note_required, is_archived, is_default) "
        "VALUES (gen_random_uuid(), now(), now(), :board, :purpose, :code, :name, "
        ":position, :note_required, false, true)"
    )
    position: dict[tuple[str, str], int] = {}
    bind = op.get_bind()
    for board, purpose, code, name, note_required in SEEDS:
        position[(board, purpose)] = position.get((board, purpose), 0) + 1
        bind.execute(
            insert,
            {
                "board": board,
                "purpose": purpose,
                "code": code,
                "name": name,
                "position": position[(board, purpose)],
                "note_required": note_required,
            },
        )


def downgrade() -> None:
    op.drop_table("board_reasons")
