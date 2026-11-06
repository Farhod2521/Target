"""Rassilka to chosen accounts: `broadcasts.audience` ("all" for every
broadcast so far) and `broadcast_targets`. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = (
    "ALTER TABLE broadcasts "
    "ADD COLUMN IF NOT EXISTS audience varchar(16) NOT NULL DEFAULT 'all'",
    """
    CREATE TABLE IF NOT EXISTS broadcast_targets (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        broadcast_id uuid NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        CONSTRAINT uniq_broadcast_target UNIQUE (broadcast_id, owner_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_broadcast_targets_owner_id "
    "ON broadcast_targets (owner_id)",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS broadcast_targets")
    op.execute("ALTER TABLE broadcasts DROP COLUMN IF EXISTS audience")
