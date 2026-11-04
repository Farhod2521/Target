"""Video darsliklar: `tutorials`, written in the office and watched in the
cabinet. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE = """
    CREATE TABLE IF NOT EXISTS tutorials (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        title varchar(200) NOT NULL DEFAULT '',
        type varchar(16) NOT NULL DEFAULT 'meta',
        description text NOT NULL DEFAULT '',
        image varchar(255) NOT NULL DEFAULT '',
        video_url varchar(500) NOT NULL DEFAULT '',
        video_file varchar(255) NOT NULL DEFAULT '',
        is_active boolean NOT NULL DEFAULT false,
        created_by_id uuid REFERENCES users(id) ON DELETE SET NULL
    )
"""
INDEXES = (
    "CREATE INDEX IF NOT EXISTS tutorials_active_created_idx "
    "ON tutorials (is_active, created_at)",
)


def upgrade() -> None:
    op.execute(CREATE)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tutorials")
