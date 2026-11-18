"""What clients say about the assistant's answers.

Asked when the assistant prepares a request to Support (``ticket``), and the
👍/👎 under any answer (``rating``, one per answer); the office reads them on
«Meta & AI». Additive and idempotent: nothing existing is changed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0067"
down_revision: str | Sequence[str] | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_feedback (
            id uuid PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            owner_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            session_id uuid NULL REFERENCES assistant_sessions (id) ON DELETE SET NULL,
            message_id uuid NULL REFERENCES assistant_messages (id) ON DELETE SET NULL,
            question text NOT NULL DEFAULT '',
            answer text NOT NULL DEFAULT '',
            ticket_summary text NOT NULL DEFAULT '',
            kind varchar(8) NOT NULL DEFAULT 'ticket',
            rating varchar(8) NOT NULL DEFAULT '',
            reason varchar(16) NOT NULL DEFAULT '',
            feedback text NOT NULL DEFAULT '',
            language varchar(8) NOT NULL DEFAULT '',
            status varchar(16) NOT NULL DEFAULT 'open',
            closed_at timestamptz NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS assistant_feedback_status_idx"
        " ON assistant_feedback (status, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assistant_feedback_owner_id"
        " ON assistant_feedback (owner_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_assistant_rating_per_message"
        " ON assistant_feedback (message_id) WHERE kind = 'rating'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assistant_feedback_session_id"
        " ON assistant_feedback (session_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assistant_feedback")
