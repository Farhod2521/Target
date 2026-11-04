"""Who a business sells to and where it works: a new advert starts from them.

`businesses.audience_gender` (all / female / male) and `businesses.regions`,
the places the owner picked from the provider's search. Additive and
idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE businesses "
        "ADD COLUMN IF NOT EXISTS audience_gender varchar(8) NOT NULL DEFAULT 'all'"
    )
    op.execute(
        "ALTER TABLE businesses "
        "ADD COLUMN IF NOT EXISTS regions jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE businesses DROP COLUMN IF EXISTS regions")
    op.execute("ALTER TABLE businesses DROP COLUMN IF EXISTS audience_gender")
