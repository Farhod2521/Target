"""The portfolio a page and an ad account sit in, for the page picker.

`page_accounts.business_external_id / business_name / business_ids /
business_state` and `ad_accounts.business_ids`. Additive and idempotent;
filled by the next page and account sync.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0051"
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE page_accounts ADD COLUMN IF NOT EXISTS "
    "business_external_id varchar(64) NOT NULL DEFAULT ''",
    "ALTER TABLE page_accounts ADD COLUMN IF NOT EXISTS "
    "business_name varchar(255) NOT NULL DEFAULT ''",
    "ALTER TABLE page_accounts ADD COLUMN IF NOT EXISTS "
    "business_ids varchar(64)[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE page_accounts ADD COLUMN IF NOT EXISTS "
    "business_state varchar(16) NOT NULL DEFAULT ''",
    "ALTER TABLE ad_accounts ADD COLUMN IF NOT EXISTS "
    "business_ids varchar(64)[] NOT NULL DEFAULT '{}'",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS business_ids")
    for column in (
        "business_state",
        "business_ids",
        "business_name",
        "business_external_id",
    ):
        op.execute(f"ALTER TABLE page_accounts DROP COLUMN IF EXISTS {column}")
