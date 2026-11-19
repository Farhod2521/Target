"""A guard finding's answer checked before it is carried out, and its outcome.

``agent_guard_alerts`` gains:

- ``answer_log_id``: the change the owner's answer opened at the provider;
- ``pending_answer`` / ``pending_state`` / ``pending_at``: an answer pressed
  more than half an hour after the figures it was given on, waiting for
  today's figures to be read again (``checking``) or for the owner to say it
  is still wanted now that the finding is gone (``confirm``);
- ``now_figures``: what that second look found;
- ``result`` / ``result_text``: whether the latest change - the guard's own
  stop or the owner's answer - landed (``applied``) or not (``failed``),
  and the provider's reason in the owner's words.

Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0069"
down_revision: str | Sequence[str] | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agent_guard_alerts"
COLUMNS = (
    ("answer_log_id", "uuid NULL"),
    ("pending_answer", "varchar(16) NOT NULL DEFAULT ''"),
    ("pending_state", "varchar(16) NOT NULL DEFAULT ''"),
    ("pending_at", "timestamptz NULL"),
    ("now_figures", "jsonb NOT NULL DEFAULT '{}'::jsonb"),
    ("result", "varchar(16) NOT NULL DEFAULT ''"),
    ("result_text", "text NOT NULL DEFAULT ''"),
)


def upgrade() -> None:
    for name, kind in COLUMNS:
        op.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {name} {kind}")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS agent_guard_answer_log "
        f"ON {TABLE} (answer_log_id) WHERE answer_log_id IS NOT NULL"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS agent_guard_action_log "
        f"ON {TABLE} (action_log_id) WHERE action_log_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS agent_guard_action_log")
    op.execute("DROP INDEX IF EXISTS agent_guard_answer_log")
    for name, _kind in reversed(COLUMNS):
        op.execute(f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {name}")
