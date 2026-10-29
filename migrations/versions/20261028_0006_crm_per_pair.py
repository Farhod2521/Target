"""A CRM of its own for every page and ad account pair.

Adds ``page_id`` and ``ad_account_id`` to the CRM's setups, stages, lost
reasons, members and cards, and lets an owner hold one setup per pair
instead of one in all. Additive and idempotent: columns and indexes are
created only when missing, and no row is deleted.

The Django project kept one CRM per owner. :func:`assign_pairs` then hands
those rows out: the owner's own rows go to the pair the cabinet is on, the
other pairs get a copy of the setup, columns and reasons, every card goes
to its lead's pair and every manager to the pair they hold most cards in.
A card no pair takes keeps nulls and stays in the database, off the board.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.orm import Session

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("crm_setups", "crm_stages", "crm_lost_reasons", "crm_members", "crm_cards")


def upgrade() -> None:
    from app.modules.crm.backfill import assign_pairs

    for table in TABLES:
        op.execute(
            f"ALTER TABLE {table} "
            "ADD COLUMN IF NOT EXISTS page_id uuid NULL "
            "REFERENCES page_accounts (id) DEFERRABLE INITIALLY DEFERRED, "
            "ADD COLUMN IF NOT EXISTS ad_account_id uuid NULL "
            "REFERENCES ad_accounts (id) DEFERRABLE INITIALLY DEFERRED"
        )
    for table in ("crm_stages", "crm_lost_reasons", "crm_members"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_pair_idx "
            f"ON {table} (owner_id, page_id, ad_account_id)"
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS crm_cards_pair_stage_idx "
        "ON crm_cards (owner_id, page_id, ad_account_id, stage_id)"
    )
    op.execute(
        "ALTER TABLE crm_setups DROP CONSTRAINT IF EXISTS uniq_crm_setup_per_owner"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_crm_setup_per_pair "
        "ON crm_setups (owner_id, page_id, ad_account_id)"
    )
    # The backfill loads User through today's model, which already reads the
    # column 0007 adds; without it a run from 0001 to head fails here.
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at timestamptz NULL"
    )
    report = assign_pairs(Session(bind=op.get_bind()))
    print(report.summary())


def downgrade() -> None:
    raise RuntimeError(
        "0006 is one way: an owner may now hold a CRM per pair, which the "
        "one-setup-per-owner schema cannot hold. Restore the backup instead."
    )
