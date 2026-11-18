"""The questions the assistant could not answer, and the office's texts on
their way into the other languages.

``assistant_gaps`` is new. ``translation`` on a refusal answer and on a help
article says whether the other languages are being written from the one the
office saved. Additive and idempotent: nothing existing is changed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_gaps (
            id uuid PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            topic varchar(255) NOT NULL DEFAULT '',
            kind varchar(16) NOT NULL DEFAULT 'answer',
            missing text NOT NULL DEFAULT '',
            question text NOT NULL DEFAULT '',
            language varchar(8) NOT NULL DEFAULT '',
            queries jsonb NOT NULL DEFAULT '[]'::jsonb,
            samples jsonb NOT NULL DEFAULT '[]'::jsonb,
            hits integer NOT NULL DEFAULT 1,
            last_asked_at timestamptz NOT NULL DEFAULT now(),
            status varchar(16) NOT NULL DEFAULT 'open',
            article_id uuid NULL REFERENCES help_articles (id) ON DELETE SET NULL,
            closed_at timestamptz NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS assistant_gaps_status_idx"
        " ON assistant_gaps (status, hits DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS assistant_gaps_recent_idx"
        " ON assistant_gaps (last_asked_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assistant_gaps_article_id"
        " ON assistant_gaps (article_id)"
    )
    op.execute(
        "ALTER TABLE help_articles"
        " ADD COLUMN IF NOT EXISTS translation varchar(16) NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE chat_refusal_answers"
        " ADD COLUMN IF NOT EXISTS translation varchar(16) NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE chat_refusal_answers DROP COLUMN IF EXISTS translation")
    op.execute("ALTER TABLE help_articles DROP COLUMN IF EXISTS translation")
    op.execute("DROP TABLE IF EXISTS assistant_gaps")
