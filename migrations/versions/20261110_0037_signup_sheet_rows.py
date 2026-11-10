"""Sign-ups already written to the sales team's sheet of those who did not
pay: `signup_sheet_rows`. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS signup_sheet_rows (
        owner_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        written_at timestamptz NOT NULL
    )
    """,
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS signup_sheet_rows")
