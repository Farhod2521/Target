"""Businesses: the people who work in one, and what each may do.

Schema (additive):

- ``business_members``: one person in one business, with the roles the
  owner picked, the ROP mark, and ``crm_member_id`` on a membership kept
  level with a CRM manager's row;
- ``business_member_grants``: what a member may do, one row per area
  (``ads`` or ``crm``) and network, to ``view`` or to ``edit``.

No row changes: ``python -m app.modules.businesses.backfill --apply`` makes
a membership for every CRM manager whose pair is a business. ``crm_members``
is not touched. The downgrade drops both tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0086"
down_revision: str | Sequence[str] | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "business_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "roles", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("is_rop", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "crm_member_id",
            sa.Uuid(),
            sa.ForeignKey("crm_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("business_id", "user_id", name="uniq_business_member"),
        sa.UniqueConstraint("crm_member_id", name="business_members_crm_member_id_key"),
    )
    op.create_index(
        "ix_business_members_created_at", "business_members", ["created_at"]
    )
    op.create_index(
        "ix_business_members_business_id", "business_members", ["business_id"]
    )
    op.create_index("ix_business_members_owner_id", "business_members", ["owner_id"])
    op.create_index(
        "business_members_user_idx", "business_members", ["user_id", "is_active"]
    )
    op.create_table(
        "business_member_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "member_id",
            sa.Uuid(),
            sa.ForeignKey("business_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("area", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("level", sa.String(8), nullable=False),
        sa.UniqueConstraint(
            "member_id", "area", "provider", name="uniq_business_member_grant"
        ),
    )
    op.create_index(
        "ix_business_member_grants_member_id", "business_member_grants", ["member_id"]
    )


def downgrade() -> None:
    op.drop_table("business_member_grants")
    op.drop_table("business_members")
