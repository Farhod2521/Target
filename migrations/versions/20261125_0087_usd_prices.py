"""Dollar prices for plans, and the account's country.

Schema (additive):

- ``plans.price_usd_cents``, ``plans.extra_page_price_usd_cents``,
  ``plans.crm_seat_price_usd_cents``: what an account outside Uzbekistan is
  shown and billed (in so'm, at the day's rate); 0 for every plan, so nothing
  changes until the office sets them;
- ``invoices.usd_rate``: so'm per dollar a bill was priced at from the
  dollar prices; "" for every bill so far;
- ``users.country``: the account's ISO country. Accounts with an Uzbek phone
  are set to ``UZ``; the rest are filled from their address on their next
  visit.

The downgrade drops the five columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0087"
down_revision: str | Sequence[str] | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICES = ("price_usd_cents", "extra_page_price_usd_cents", "crm_seat_price_usd_cents")


def upgrade() -> None:
    for name in PRICES:
        op.add_column(
            "plans",
            sa.Column(name, sa.BigInteger(), nullable=False, server_default="0"),
        )
    op.add_column(
        "invoices",
        sa.Column("usd_rate", sa.String(32), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("country", sa.String(2), nullable=False, server_default=""),
    )
    op.execute(
        sa.text(
            "UPDATE users SET country = 'UZ' "
            "WHERE regexp_replace(phone, '[^0-9]', '', 'g') LIKE '998%'"
        )
    )


def downgrade() -> None:
    op.drop_column("users", "country")
    op.drop_column("invoices", "usd_rate")
    for name in PRICES:
        op.drop_column("plans", name)
