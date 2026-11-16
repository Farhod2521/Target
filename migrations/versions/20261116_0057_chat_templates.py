"""Named templates for a chat advert: `chat_templates`.

«Xabar yozishsin» asks for a greeting, the ready questions under it and the
answer sent by itself for each. An owner keeps them under a name and opens the next advert on the same page
with it. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0057"
down_revision: str | Sequence[str] | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS chat_templates (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        page_id uuid NULL REFERENCES page_accounts (id) ON DELETE CASCADE,
        name varchar(40) NOT NULL DEFAULT '',
        welcome_text text NOT NULL DEFAULT '',
        questions jsonb NOT NULL DEFAULT '[]'::jsonb,
        answers jsonb NOT NULL DEFAULT '[]'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_chat_templates_page_id ON chat_templates (page_id)",
    "CREATE INDEX IF NOT EXISTS chat_template_page_idx ON chat_templates (owner_id, page_id)",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_templates")
