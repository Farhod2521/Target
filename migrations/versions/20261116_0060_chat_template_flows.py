"""chat_templates.meta_flow_id + meta_state

A saved «Xabar yozishsin» template is also kept on the page as a welcome
message flow, so Ads Manager offers it. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0060"
down_revision: str | Sequence[str] | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE chat_templates ADD COLUMN IF NOT EXISTS meta_flow_id varchar(64) NOT NULL DEFAULT ''",
    "ALTER TABLE chat_templates ADD COLUMN IF NOT EXISTS meta_state varchar(16) NOT NULL DEFAULT ''",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE chat_templates DROP COLUMN IF EXISTS meta_state")
    op.execute("ALTER TABLE chat_templates DROP COLUMN IF EXISTS meta_flow_id")
