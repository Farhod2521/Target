"""The one chat: `assistant_sessions`, `assistant_messages`, `help_articles`.

A new chat beside the old one (`chat_sessions`, `chat_messages`), which is
not touched. A thread holds the client's words, the assistant's answers and
the replies of a person in Support (`author`: user, ai, staff). A row that
is a support-chat message carries `support_message_id` - unique, so one
message is never shown twice; no foreign key, the support chat erases its
own rows. `help_articles` is the office's list of known problems and their
steps, which the assistant searches. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS assistant_sessions (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
        title varchar(120) NOT NULL DEFAULT '',
        page_id uuid NULL REFERENCES page_accounts (id) ON DELETE SET NULL,
        ad_account_id uuid NULL REFERENCES ad_accounts (id) ON DELETE SET NULL,
        last_message_at timestamptz NULL,
        support_at timestamptz NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_assistant_sessions_created_at ON assistant_sessions (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_assistant_sessions_owner_id ON assistant_sessions (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_assistant_sessions_page_id ON assistant_sessions (page_id)",
    "CREATE INDEX IF NOT EXISTS ix_assistant_sessions_ad_account_id ON assistant_sessions (ad_account_id)",
    "CREATE INDEX IF NOT EXISTS assistant_session_recent_idx ON assistant_sessions (owner_id, last_message_at DESC)",
    "CREATE INDEX IF NOT EXISTS assistant_session_support_idx ON assistant_sessions (owner_id, support_at DESC) WHERE support_at IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS assistant_messages (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
        session_id uuid NOT NULL REFERENCES assistant_sessions (id) ON DELETE CASCADE,
        author varchar(16) NOT NULL DEFAULT '',
        text text NOT NULL DEFAULT '',
        html text NOT NULL DEFAULT '',
        status varchar(16) NOT NULL DEFAULT 'done',
        masked_figures integer NOT NULL DEFAULT 0,
        buttons jsonb NOT NULL DEFAULT '[]'::jsonb,
        replies jsonb NOT NULL DEFAULT '[]'::jsonb,
        meta jsonb NOT NULL DEFAULT '{}'::jsonb,
        support_message_id uuid NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_assistant_messages_created_at ON assistant_messages (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_assistant_messages_owner_id ON assistant_messages (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_assistant_messages_session_id ON assistant_messages (session_id)",
    "CREATE INDEX IF NOT EXISTS assistant_thread_idx ON assistant_messages (owner_id, session_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS assistant_messages_support_message_uniq ON assistant_messages (support_message_id) WHERE support_message_id IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS help_articles (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        code varchar(64) NOT NULL UNIQUE,
        problem_uz varchar(255) NOT NULL DEFAULT '',
        problem_ru varchar(255) NOT NULL DEFAULT '',
        problem_en varchar(255) NOT NULL DEFAULT '',
        steps_uz text NOT NULL DEFAULT '',
        steps_ru text NOT NULL DEFAULT '',
        steps_en text NOT NULL DEFAULT '',
        keywords text NOT NULL DEFAULT '',
        is_published boolean NOT NULL DEFAULT false,
        position integer NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_help_articles_created_at ON help_articles (created_at)",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS help_articles")
    op.execute("DROP TABLE IF EXISTS assistant_messages")
    op.execute("DROP TABLE IF EXISTS assistant_sessions")
