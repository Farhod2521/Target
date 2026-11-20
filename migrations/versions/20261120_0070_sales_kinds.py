"""Sales: kinds of lead per manager, how a card was taken, and Start cards
back in Ishlanmagan.

Schema (additive):

- ``board_sales_kinds``: the kinds of lead each Sales manager takes first; a
  manager with no row takes every kind, so nothing changes until the Owner
  sets one;
- ``board_cards.taken_as``: the kind a card was when its manager took it,
  or ``phone``; empty for cards taken before.

Cards (the new rule: a discount card reaches a 20%/10% column only after a
manager talked to the client, and its end no longer closes it):

1. open cards in 20%/10% with nobody on them go back to Ishlanmagan;
2. open cards in 20%/10% whose manager never reached the client go to
   Yangi lead (never called) or Bog'lanilmadi (called, not reached);
3. Start buyers' cards the discount's end closed («Chegirma tugadi»), with
   no full plan bought: reopened, in Bog'lanildi with their manager when the
   manager talked to them, otherwise in Ishlanmagan with nobody.

Each moved card gets a «moved» line saying why. No row is deleted. The
downgrade drops the table and the column; moved cards stay where they are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | Sequence[str] | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTE = (
    "Yangi qoida: chegirma ustuniga faqat menejer gaplashgandan keyin "
    "o'tiladi, chegirma tugashi kartani yopmaydi."
)
OFFER = "('discount_20', 'discount_10')"

START_PAID = """
    SELECT 1 FROM invoices i JOIN plans p ON p.id = i.plan_id
    WHERE i.owner_id = c.owner_id AND i.kind = 'plan' AND i.status = 'paid'
      AND p.code = 'start'
"""
FULL_PAID = """
    SELECT 1 FROM invoices i JOIN plans p ON p.id = i.plan_id
    WHERE i.owner_id = c.owner_id AND i.kind = 'plan'
      AND i.status IN ('paid', 'refunded')
      AND p.code <> 'start' AND p.is_one_time IS false
"""


def _move(where: str, to: str, extra: str = "") -> str:
    """Move the cards ``where`` picks into ``to`` (an SQL expression over
    ``c``) and write each its line, in one statement."""
    return f"""
        WITH moved AS (
            UPDATE board_cards c
            SET column_code = {to}, column_since = now(), updated_at = now(){extra}
            FROM board_cards o
            WHERE o.id = c.id AND c.board = 'sales' AND {where}
            RETURNING c.id, c.owner_id, o.column_code AS before, c.column_code AS after
        )
        INSERT INTO board_card_events
            (id, card_id, owner_id, kind, from_column, to_column, actor_id,
             body, ref, created_at)
        SELECT gen_random_uuid(), id, owner_id, 'moved', before, after, NULL,
               :note, '', now()
        FROM moved
    """


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS board_sales_kinds (
            member_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            kind varchar(16) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            set_by_id uuid NULL REFERENCES users (id) ON DELETE SET NULL,
            PRIMARY KEY (member_id, kind)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_board_sales_kinds_set_by_id"
        " ON board_sales_kinds (set_by_id)"
    )
    op.execute(
        "ALTER TABLE board_cards"
        " ADD COLUMN IF NOT EXISTS taken_as varchar(16) NOT NULL DEFAULT ''"
    )

    bind = op.get_bind()
    note = {"note": NOTE}
    # 1. Nobody on it: back to the queue.
    bind.execute(
        sa.text(
            _move(
                f"c.closed_at IS NULL AND c.manager_id IS NULL"
                f" AND c.column_code IN {OFFER}",
                "'unworked'",
                ", due_at = NULL",
            )
        ),
        note,
    )
    # 2. A manager has it but never reached the client.
    bind.execute(
        sa.text(
            _move(
                f"c.closed_at IS NULL AND c.manager_id IS NOT NULL"
                f" AND c.column_code IN {OFFER} AND c.contact_mark <> 'contacted'",
                "CASE WHEN c.contact_mark = 'no_contact' THEN 'no_contact'"
                " ELSE 'new_lead' END",
            )
        ),
        note,
    )
    # 3. Start buyers the discount's end closed.
    bind.execute(
        sa.text(
            _move(
                "c.closed_at IS NOT NULL AND c.column_code = 'closed'"
                " AND c.close_reason = 'offer_ended'"
                f" AND EXISTS ({START_PAID}) AND NOT EXISTS ({FULL_PAID})",
                "CASE WHEN c.manager_id IS NOT NULL"
                " AND c.contact_mark = 'contacted' THEN 'contacted'"
                " ELSE 'unworked' END",
                ", closed_at = NULL, close_reason = '', close_note = ''"
                ", manager_id = CASE WHEN c.manager_id IS NOT NULL"
                " AND c.contact_mark = 'contacted' THEN c.manager_id END"
                ", due_at = NULL",
            )
        ),
        note,
    )


def downgrade() -> None:
    op.execute("ALTER TABLE board_cards DROP COLUMN IF EXISTS taken_as")
    op.execute("DROP TABLE IF EXISTS board_sales_kinds")
