"""Each step of a CRM card across the board, and nothing else.

Schema (additive): ``crm_stage_moves`` - the column a card left, the one it
entered and when - written from now on whenever a card changes column. The
table is empty after the migration; the steps of the cards already on the
boards are put together from their history by
``python -m app.modules.crm.moves --apply`` (rows marked ``rebuilt``). The
downgrade drops the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0073"
down_revision: str | Sequence[str] | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS crm_stage_moves ("
        "id uuid PRIMARY KEY, "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "updated_at timestamptz NOT NULL DEFAULT now(), "
        "owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, "
        "card_id uuid NOT NULL REFERENCES crm_cards(id) ON DELETE CASCADE, "
        "from_stage_id uuid, "
        "from_kind varchar(8) NOT NULL DEFAULT '', "
        "to_stage_id uuid NOT NULL, "
        "to_kind varchar(8) NOT NULL DEFAULT '', "
        "at timestamptz NOT NULL DEFAULT now(), "
        "rebuilt boolean NOT NULL DEFAULT false)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS crm_stage_moves_card_at_idx "
        "ON crm_stage_moves (card_id, at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crm_stage_moves_owner_id "
        "ON crm_stage_moves (owner_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crm_stage_moves_created_at "
        "ON crm_stage_moves (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS crm_stage_moves")
