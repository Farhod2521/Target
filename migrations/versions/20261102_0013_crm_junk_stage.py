"""Every board ends in «Sifatsiz lid».

One column per pair, after «Rad etildi», for the boards that exist already; a
new board gets it from its setup. A row no pair could take keeps no board.
Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADD_COLUMN = """
    INSERT INTO crm_stages (
        id, created_at, updated_at, owner_id, page_id, ad_account_id,
        name, color, kind, position, counts_as_quality
    )
    SELECT gen_random_uuid(), now(), now(), owner_id, page_id, ad_account_id,
           'Sifatsiz lid', '#4A5878', 'junk', max(position) + 1, false
    FROM crm_stages
    WHERE page_id IS NOT NULL AND ad_account_id IS NOT NULL
    GROUP BY owner_id, page_id, ad_account_id
    HAVING bool_and(kind <> 'junk')
"""


def upgrade() -> None:
    op.execute(ADD_COLUMN)


def downgrade() -> None:
    """The column may hold cards by now; nothing is taken back."""
