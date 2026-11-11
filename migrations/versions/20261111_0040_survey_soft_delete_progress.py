"""Surveys are never removed, and an answer is kept question by question.

`surveys.deleted_at`: a deleted survey is closed and left out of the office's
list; its questions and answers stay. `survey_responses.completed_at`: null
while the customer is still answering, set when they finish. Every answer
already written was finished, so it is stamped with its own creation time.
Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE surveys ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL"
    )
    op.execute(
        "ALTER TABLE survey_responses "
        "ADD COLUMN IF NOT EXISTS completed_at timestamptz NULL"
    )
    op.execute(
        "UPDATE survey_responses SET completed_at = created_at "
        "WHERE completed_at IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE survey_responses DROP COLUMN IF EXISTS completed_at")
    op.execute("ALTER TABLE surveys DROP COLUMN IF EXISTS deleted_at")
