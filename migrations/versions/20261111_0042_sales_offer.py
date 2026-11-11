"""The sales manager's offer (20% for a day, then 10% until day three).

`invoices.offer_minor`: what the offer took off a bill, so a bill priced
again gets it back first, as a promo code's discount is. The Sales board's
20% / 10% / Chegirmasiz columns are shown, placed right after Bog'lanildi;
Sinovda stays hidden until the trial is built.

Additive and idempotent: a column with a default, and an update of three
board rows. Running it again changes nothing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OFFER_COLUMNS = ("discount_20", "discount_10", "no_discount")
AFTER = "contacted"


def _place(conn: sa.Connection) -> None:
    """The visible columns in their order, the offer ones after Bog'lanildi,
    hidden ones after them all, numbered from 1."""
    rows = conn.execute(
        sa.text(
            "SELECT code, is_visible FROM board_columns WHERE board = 'sales' "
            "ORDER BY position, code"
        )
    ).all()
    shown = [code for code, visible in rows if visible and code not in OFFER_COLUMNS]
    offers = [code for code in OFFER_COLUMNS if code in {r[0] for r in rows}]
    if AFTER in shown:
        at = shown.index(AFTER) + 1
        shown[at:at] = offers
    else:
        shown += offers
    hidden = [code for code, visible in rows if not visible and code not in offers]
    for position, code in enumerate(shown + hidden, start=1):
        conn.execute(
            sa.text(
                "UPDATE board_columns SET position = :p "
                "WHERE board = 'sales' AND code = :c AND position <> :p"
            ),
            {"p": position, "c": code},
        )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE invoices "
        "ADD COLUMN IF NOT EXISTS offer_minor bigint NOT NULL DEFAULT 0"
    )
    conn = op.get_bind()
    hidden = conn.execute(
        sa.text(
            "SELECT count(*) FROM board_columns WHERE board = 'sales' "
            "AND code = ANY(:codes) AND NOT is_visible"
        ),
        {"codes": list(OFFER_COLUMNS)},
    ).scalar()
    if not hidden:
        return
    conn.execute(
        sa.text(
            "UPDATE board_columns SET is_visible = true, updated_at = now() "
            "WHERE board = 'sales' AND code = ANY(:codes)"
        ),
        {"codes": list(OFFER_COLUMNS)},
    )
    _place(conn)


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE board_columns SET is_visible = false, updated_at = now() "
            "WHERE board = 'sales' AND code = ANY(:codes)"
        ),
        {"codes": list(OFFER_COLUMNS)},
    )
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS offer_minor")
