"""Daily exchange rates, and nothing else.

Schema (additive): ``fx_rates`` - how many so'm one unit of a currency cost
on a day, as the Central Bank set it. It is empty after the migration: run
``python -m app.modules.metrics.rates`` once to read the past year. The
downgrade drops the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0072"
down_revision: str | Sequence[str] | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS fx_rates ("
        "day date NOT NULL, "
        "currency varchar(3) NOT NULL, "
        "rate numeric(20, 8) NOT NULL, "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "PRIMARY KEY (day, currency))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fx_rates")
