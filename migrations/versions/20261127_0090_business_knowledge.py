"""Businesses: what a kind of business is advised, the narrower kinds the
assistant finds, and what is known about each business.

Schema (additive):

- ``business_type_rules``: one row for a direction, written by the office:
  the goal to offer first and why, the second goal and when it is the better
  one, and what an advert of this kind of business must not say;
- ``business_subtypes``: a narrower kind under a direction («Oshxona
  mebeli» under «Mebel»). Made by the assistant when a customer names one
  that is not there, or by the office; one merged into another points at it;
- ``business_knowledge``: one row for a business: its narrower kind, how
  sure the kind is, and ``data``, everything the business has told us (what
  it sells, the facts about it, the changes waiting for a yes), with a
  ``version`` that grows at every write.

No row changes. The downgrade drops the three tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0090"
down_revision: str | Sequence[str] | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "business_type_rules",
        *_stamps(),
        sa.Column(
            "direction_id",
            sa.Uuid(),
            sa.ForeignKey("business_categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("goal_first", sa.String(32), nullable=False, server_default=""),
        sa.Column("reason_first", sa.Text(), nullable=False, server_default=""),
        sa.Column("goal_second", sa.String(32), nullable=False, server_default=""),
        sa.Column("when_second", sa.Text(), nullable=False, server_default=""),
        sa.Column("never_say", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "updated_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("direction_id", name="uniq_business_type_rule"),
    )
    op.create_index(
        "ix_business_type_rules_created_at", "business_type_rules", ["created_at"]
    )
    op.create_index(
        "ix_business_type_rules_updated_by_id", "business_type_rules", ["updated_by_id"]
    )
    op.create_table(
        "business_subtypes",
        *_stamps(),
        sa.Column(
            "direction_id",
            sa.Uuid(),
            sa.ForeignKey("business_categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(80), nullable=False),
        sa.Column("synonyms", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("origin", sa.String(8), nullable=False),
        sa.Column(
            "is_checked", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "merged_into_id",
            sa.Uuid(),
            sa.ForeignKey("business_subtypes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "direction_id", "name_key", name="uniq_business_subtype_name"
        ),
        sa.CheckConstraint("NOT (name_key = '')", name="business_subtype_has_a_name"),
    )
    op.create_index(
        "ix_business_subtypes_created_at", "business_subtypes", ["created_at"]
    )
    op.create_index(
        "ix_business_subtypes_direction_id", "business_subtypes", ["direction_id"]
    )
    op.create_index(
        "ix_business_subtypes_merged_into_id", "business_subtypes", ["merged_into_id"]
    )
    op.create_index(
        "ix_business_subtypes_created_by_id", "business_subtypes", ["created_by_id"]
    )
    op.create_table(
        "business_knowledge",
        *_stamps(),
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subtype_id",
            sa.Uuid(),
            sa.ForeignKey("business_subtypes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("type_state", sa.String(12), nullable=False, server_default="unset"),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("business_id", name="uniq_business_knowledge"),
    )
    op.create_index(
        "ix_business_knowledge_created_at", "business_knowledge", ["created_at"]
    )
    op.create_index(
        "ix_business_knowledge_subtype_id", "business_knowledge", ["subtype_id"]
    )


def downgrade() -> None:
    op.drop_table("business_knowledge")
    op.drop_table("business_subtypes")
    op.drop_table("business_type_rules")
