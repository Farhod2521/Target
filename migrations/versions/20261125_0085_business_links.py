"""Businesses: what a business advertises from, and the business on each row.

Schema (additive):

- ``business_links``: one network object of one business. For Meta, the page
  and ad account pair. A changed account closes the row (``unbound_at``) and
  opens another, so no row is rewritten. Two partial unique indexes over the
  open rows: one object of a kind per network in a business, and one
  business per object in the whole database;
- ``business_id`` (null) on ``crm_stages``, ``crm_lost_reasons``,
  ``crm_cards``, ``crm_members``, ``crm_setups``, ``leads``,
  ``chat_sessions`` and ``campaign_launches``, beside the page and account
  columns those rows keep.

No row changes: the links and the new column are filled by
``python -m app.modules.businesses.backfill --apply``, which may be run
again. The downgrade drops the columns and the table; every page, account
and pair column is as it was.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0085"
down_revision: str | Sequence[str] | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "crm_stages",
    "crm_lost_reasons",
    "crm_cards",
    "crm_members",
    "crm_setups",
    "leads",
    "chat_sessions",
    "campaign_launches",
)
OPEN = sa.text("unbound_at IS NULL")


def upgrade() -> None:
    op.create_table(
        "business_links",
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
        sa.Column("provider", sa.String(32), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False, server_default=""),
        sa.Column(
            "page_id",
            sa.Uuid(),
            sa.ForeignKey("page_accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "ad_account_id",
            sa.Uuid(),
            sa.ForeignKey("ad_accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("external_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_business_links_created_at", "business_links", ["created_at"])
    op.create_index("ix_business_links_business_id", "business_links", ["business_id"])
    op.create_index("ix_business_links_owner_id", "business_links", ["owner_id"])
    op.create_index(
        "ix_business_links_ad_account_id", "business_links", ["ad_account_id"]
    )
    op.create_index(
        "business_links_pair_idx", "business_links", ["page_id", "ad_account_id"]
    )
    op.create_index(
        "uniq_business_link_per_network",
        "business_links",
        ["business_id", "provider", "kind"],
        unique=True,
        postgresql_where=OPEN,
    )
    op.create_index(
        "uniq_business_link_per_object",
        "business_links",
        ["provider", "kind", "external_id"],
        unique=True,
        postgresql_where=OPEN,
    )
    for table in TABLES:
        op.add_column(table, sa.Column("business_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"{table}_business_id_fkey",
            table,
            "businesses",
            ["business_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_business_id", table, ["business_id"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_business_id", table_name=table)
        op.drop_constraint(f"{table}_business_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "business_id")
    op.drop_table("business_links")
