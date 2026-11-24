"""Boards: talked columns, rule conditions and actions, the settings journal.

Schema (additive):

- ``board_columns.is_talked``: Sales, a card standing here was talked to,
  so a Start payment starts its discount from here. True for Bog'lanildi and
  the discount columns, as the code had it; false for the rest;
- ``board_rules.conditions`` and ``board_rules.actions``: what else must
  hold of a card for one of the superuser's rules, and what the rule does
  besides or instead of moving it. Empty for every rule that exists, which
  so runs as it did;
- ``board_setting_events``: who changed a board's settings and what.

The downgrade drops the three; a rule that only told or set a time then
does nothing (it has no column to move to).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0081"
down_revision: str | Sequence[str] | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The Sales columns the code counts as talked to (START_TALKED_COLUMNS).
TALKED = ("contacted", "discount_20", "discount_10")


def upgrade() -> None:
    op.add_column(
        "board_columns",
        sa.Column("is_talked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text(
            "UPDATE board_columns SET is_talked = true "
            "WHERE board = 'sales' AND code IN :codes"
        ).bindparams(sa.bindparam("codes", value=TALKED, expanding=True))
    )
    for name in ("conditions", "actions"):
        op.add_column(
            "board_rules",
            sa.Column(
                name,
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    op.create_table(
        "board_setting_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("board", sa.String(16), nullable=False),
        sa.Column("area", sa.String(16), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "board_setting_events_board_idx",
        "board_setting_events",
        ["board", "created_at"],
    )
    op.create_index(
        "ix_board_setting_events_actor_id", "board_setting_events", ["actor_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_board_setting_events_actor_id", table_name="board_setting_events")
    op.drop_index("board_setting_events_board_idx", table_name="board_setting_events")
    op.drop_table("board_setting_events")
    op.drop_column("board_rules", "actions")
    op.drop_column("board_rules", "conditions")
    op.drop_column("board_columns", "is_talked")
