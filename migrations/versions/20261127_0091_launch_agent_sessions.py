"""Advert chat: its conversations.

Additive: one new table, nothing existing is touched.

Revision ID: 0091
Revises: 0090
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0091"
down_revision: str | Sequence[str] | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "launch_agent_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "launch_id",
            sa.Uuid(),
            sa.ForeignKey("campaign_launches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"),
        sa.Column(
            "brief",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "messages",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heard_calls", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_launch_agent_sessions_created_at", "launch_agent_sessions", ["created_at"]
    )
    op.create_index(
        "ix_launch_agent_sessions_owner_id", "launch_agent_sessions", ["owner_id"]
    )
    op.create_index(
        "ix_launch_agent_sessions_business_id",
        "launch_agent_sessions",
        ["business_id"],
    )
    op.create_index(
        "ix_launch_agent_sessions_launch_id", "launch_agent_sessions", ["launch_id"]
    )
    op.create_index(
        "launch_agent_sessions_owner_status",
        "launch_agent_sessions",
        ["owner_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("launch_agent_sessions")
