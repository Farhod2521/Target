"""The office's hold on a kept answer, and when it last wrote one.

``held`` keeps an answer from every screen until the office has read it;
``edited_at`` says the words are a person's. ``upload_refusal`` is why Meta
refused a file, for the screen that reads it after the worker has gone.
Additive and idempotent: existing rows stay shown and unedited.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chat_refusal_answers "
        "ADD COLUMN IF NOT EXISTS held boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE chat_refusal_answers "
        "ADD COLUMN IF NOT EXISTS edited_at timestamptz NULL"
    )
    op.execute(
        "ALTER TABLE launch_creatives "
        "ADD COLUMN IF NOT EXISTS upload_refusal jsonb NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE launch_creatives DROP COLUMN IF EXISTS upload_refusal")
    op.execute("ALTER TABLE chat_refusal_answers DROP COLUMN IF EXISTS edited_at")
    op.execute("ALTER TABLE chat_refusal_answers DROP COLUMN IF EXISTS held")
