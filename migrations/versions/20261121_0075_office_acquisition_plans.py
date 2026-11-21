"""The plans the office's advertising figures count, and nothing else.

Schema (additive): ``office_acquisition_plans`` - one row per plan the
superuser picked. Empty after the migration: no payment is counted until
plans are picked. The downgrade drops the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0075"
down_revision: str | Sequence[str] | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS office_acquisition_plans ("
        "plan_id uuid PRIMARY KEY REFERENCES plans(id) ON DELETE CASCADE, "
        "picked_by_id uuid NULL REFERENCES users(id) ON DELETE SET NULL, "
        "created_at timestamptz NOT NULL DEFAULT now())"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS office_acquisition_plans")
