"""What a renewal lets go once it is paid, and a page's own adverts hold.

`invoices.drop_page_ids` / `drop_member_ids`: pages and CRM managers the
owner unticked on the renewal; released when the bill lands. `lapse_holds`
gains `page_id`: a hold for one released page's adverts, beside the
owner-wide hold of a lapsed subscription. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE invoices "
        "ADD COLUMN IF NOT EXISTS drop_page_ids jsonb NOT NULL DEFAULT '[]'::jsonb, "
        "ADD COLUMN IF NOT EXISTS drop_member_ids jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE lapse_holds ADD COLUMN IF NOT EXISTS page_id uuid "
        "REFERENCES page_accounts(id) DEFERRABLE INITIALLY DEFERRED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS lapse_holds_page_idx ON lapse_holds (page_id)"
    )
    # One owner-wide hold per deadline, as before; a page's holds stand apart.
    op.execute(
        "ALTER TABLE lapse_holds DROP CONSTRAINT IF EXISTS ads_lapsehold_one_per_deadline"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ads_lapsehold_one_per_deadline "
        "ON lapse_holds (owner_id, ended_at) WHERE page_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS lapse_holds_one_per_page_release "
        "ON lapse_holds (page_id, ended_at) WHERE page_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS lapse_holds_one_per_page_release")
    op.execute("DROP INDEX IF EXISTS ads_lapsehold_one_per_deadline")
    op.execute("DELETE FROM lapse_holds WHERE page_id IS NOT NULL")
    op.execute(
        "ALTER TABLE lapse_holds ADD CONSTRAINT ads_lapsehold_one_per_deadline "
        "UNIQUE (owner_id, ended_at)"
    )
    op.execute("DROP INDEX IF EXISTS lapse_holds_page_idx")
    op.execute("ALTER TABLE lapse_holds DROP COLUMN IF EXISTS page_id")
    op.execute(
        "ALTER TABLE invoices DROP COLUMN IF EXISTS drop_page_ids, "
        "DROP COLUMN IF EXISTS drop_member_ids"
    )
