"""Google sign-in and the sign-up question "who are you": `users.role`
("" until asked) and `social_identities`. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role varchar(16) NOT NULL DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS social_identities (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider varchar(16) NOT NULL,
        subject varchar(255) NOT NULL,
        email varchar(254) NOT NULL,
        last_used_at timestamptz NULL,
        CONSTRAINT uniq_social_identity UNIQUE (provider, subject),
        CONSTRAINT uniq_social_identity_owner UNIQUE (owner_id, provider)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_social_identities_owner_id "
    "ON social_identities (owner_id)",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS social_identities")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS role")
