"""Boards: columns the superuser adds.

Schema (additive):

- ``board_columns.is_custom``: a column added in the office, not one the
  rules were written for; false for every column that exists;
- ``board_columns.created_by_id``: who added it.

No row changes. The downgrade drops both columns; a custom column's row
stays, as an ordinary one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077"
down_revision: str | Sequence[str] | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "board_columns",
        sa.Column("is_custom", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("board_columns", sa.Column("created_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "board_columns_created_by_id_fkey",
        "board_columns",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_board_columns_created_by_id", "board_columns", ["created_by_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_board_columns_created_by_id", table_name="board_columns")
    op.drop_constraint(
        "board_columns_created_by_id_fkey", "board_columns", type_="foreignkey"
    )
    op.drop_column("board_columns", "created_by_id")
    op.drop_column("board_columns", "is_custom")
