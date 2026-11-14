"""The renewal board: a card for each term that runs out.

A card of «Uzaytirish» carries the plan, the moment the term ends and the
bill that renewed it. One client may have many such cards, one per term, so
the one-card-per-client index now holds only for cards without a term (Sales
and Support, as before), and a second index keeps one card per term.

The board's default manager is kept beside its live moment.

Additive: no row is changed or deleted. The board's own columns are seeded
by the first read, as a new board's always are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | Sequence[str] | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = (
    "ALTER TABLE board_cards ADD COLUMN IF NOT EXISTS plan_code varchar(32) NOT NULL DEFAULT ''",
    "ALTER TABLE board_cards ADD COLUMN IF NOT EXISTS term_ends_at timestamptz NULL",
    "ALTER TABLE board_cards ADD COLUMN IF NOT EXISTS invoice_id uuid NULL "
    "REFERENCES invoices(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_board_cards_invoice_id ON board_cards (invoice_id)",
    "DROP INDEX IF EXISTS uniq_board_card_owner",
    "CREATE UNIQUE INDEX uniq_board_card_owner ON board_cards (board, owner_id) "
    "WHERE term_ends_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_board_card_term ON board_cards "
    "(board, owner_id, term_ends_at) WHERE term_ends_at IS NOT NULL",
    "ALTER TABLE board_settings ADD COLUMN IF NOT EXISTS manager_id uuid NULL "
    "REFERENCES users(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_board_settings_manager_id ON board_settings (manager_id)",
)

# The renewal cards go with their board: with them left, the one-card index
# could not be put back.
DOWNGRADE = (
    "DELETE FROM board_cards WHERE board = 'renewal'",
    "DELETE FROM board_columns WHERE board = 'renewal'",
    "DELETE FROM board_settings WHERE board = 'renewal'",
    "DROP INDEX IF EXISTS uniq_board_card_term",
    "DROP INDEX IF EXISTS uniq_board_card_owner",
    "CREATE UNIQUE INDEX uniq_board_card_owner ON board_cards (board, owner_id)",
    "DROP INDEX IF EXISTS ix_board_settings_manager_id",
    "ALTER TABLE board_settings DROP COLUMN IF EXISTS manager_id",
    "DROP INDEX IF EXISTS ix_board_cards_invoice_id",
    "ALTER TABLE board_cards DROP COLUMN IF EXISTS invoice_id",
    "ALTER TABLE board_cards DROP COLUMN IF EXISTS term_ends_at",
    "ALTER TABLE board_cards DROP COLUMN IF EXISTS plan_code",
)


def upgrade() -> None:
    conn = op.get_bind()
    for statement in UPGRADE:
        conn.execute(sa.text(statement))


def downgrade() -> None:
    conn = op.get_bind()
    for statement in DOWNGRADE:
        conn.execute(sa.text(statement))
