"""The office boards, version 2: `board_settings`, `board_columns`,
`board_cards`, `board_card_events`, `survey_help_options`.

Additive and idempotent: only new tables. Each board's live moment is the
time this runs, so sign-ups and events before the deploy stay off the
boards; running it again keeps the first moment.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | Sequence[str] | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (board, code, name, kind, is_final, is_visible) in their first order;
# app/modules/boards/constants.py SEED_COLUMNS says the same.
COLUMNS = (
    ("sales", "unworked", "Ishlanmagan", "auto", False, True),
    ("sales", "new_lead", "Yangi lead", "manual", False, True),
    ("sales", "no_contact", "Bog'lanilmadi", "manual", False, True),
    ("sales", "contacted", "Bog'lanildi", "manual", False, True),
    ("sales", "trial", "Sinovda", "auto", False, False),
    ("sales", "discount_20", "20% chegirma", "auto", False, False),
    ("sales", "discount_10", "10% chegirma", "auto", False, False),
    ("sales", "no_discount", "Chegirmasiz", "auto", False, False),
    ("sales", "sold", "Sotildi", "auto", True, True),
    ("sales", "closed", "Yopildi", "manual", True, True),
    ("support", "new", "Yangi", "auto", False, True),
    ("support", "in_progress", "Ishlanmoqda", "manual", False, True),
    ("support", "resolved", "Hal qilindi", "manual", True, True),
)

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS board_settings (
        board varchar(16) PRIMARY KEY,
        live_since timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS board_columns (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        board varchar(16) NOT NULL,
        code varchar(24) NOT NULL,
        name varchar(40) NOT NULL,
        position smallint NOT NULL,
        kind varchar(16) NOT NULL,
        is_final boolean NOT NULL DEFAULT false,
        is_visible boolean NOT NULL DEFAULT true,
        updated_by_id uuid NULL REFERENCES users(id) ON DELETE SET NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_board_column_code ON board_columns (board, code)",
    "CREATE INDEX IF NOT EXISTS board_columns_order_idx ON board_columns (board, position)",
    "CREATE INDEX IF NOT EXISTS ix_board_columns_updated_by_id ON board_columns (updated_by_id)",
    """
    CREATE TABLE IF NOT EXISTS board_cards (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        board varchar(16) NOT NULL,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        column_code varchar(24) NOT NULL,
        manager_id uuid NULL REFERENCES users(id) ON DELETE SET NULL,
        contact_mark varchar(16) NOT NULL DEFAULT '',
        needs_support boolean NOT NULL DEFAULT false,
        reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
        opened_at timestamptz NOT NULL,
        column_since timestamptz NOT NULL,
        closed_at timestamptz NULL,
        close_reason varchar(24) NOT NULL DEFAULT '',
        close_note text NOT NULL DEFAULT ''
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_board_card_owner ON board_cards (board, owner_id)",
    "CREATE INDEX IF NOT EXISTS board_cards_column_idx ON board_cards (board, column_code, column_since)",
    "CREATE INDEX IF NOT EXISTS board_cards_manager_idx ON board_cards (board, manager_id)",
    "CREATE INDEX IF NOT EXISTS ix_board_cards_owner_id ON board_cards (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_board_cards_manager_id ON board_cards (manager_id)",
    """
    CREATE TABLE IF NOT EXISTS board_card_events (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        card_id uuid NOT NULL REFERENCES board_cards(id) ON DELETE CASCADE,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind varchar(24) NOT NULL,
        from_column varchar(24) NOT NULL DEFAULT '',
        to_column varchar(24) NOT NULL DEFAULT '',
        actor_id uuid NULL REFERENCES users(id) ON DELETE SET NULL,
        body text NOT NULL DEFAULT '',
        ref varchar(100) NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS board_card_events_card_idx ON board_card_events (card_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_board_card_event_ref ON board_card_events (card_id, ref) WHERE ref <> ''",
    "CREATE INDEX IF NOT EXISTS ix_board_card_events_owner_id ON board_card_events (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_board_card_events_actor_id ON board_card_events (actor_id)",
    """
    CREATE TABLE IF NOT EXISTS survey_help_options (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        question_id uuid NOT NULL REFERENCES survey_questions(id) ON DELETE CASCADE,
        option_index smallint NOT NULL,
        set_by_id uuid NULL REFERENCES users(id) ON DELETE SET NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_survey_help_option ON survey_help_options (question_id, option_index)",
    "CREATE INDEX IF NOT EXISTS ix_survey_help_options_set_by_id ON survey_help_options (set_by_id)",
)


LIVE = (
    "INSERT INTO board_settings (board, live_since, updated_at) "
    "VALUES ('sales', now(), now()), ('support', now(), now()) "
    "ON CONFLICT (board) DO NOTHING"
)
SEED = (
    "INSERT INTO board_columns (id, created_at, updated_at, board, code, name, "
    "position, kind, is_final, is_visible) VALUES (gen_random_uuid(), now(), "
    "now(), :board, :code, :name, :position, :kind, :is_final, :is_visible) "
    "ON CONFLICT (board, code) DO NOTHING"
)


def _seeds() -> list[sa.TextClause]:
    """One insert per column, numbered from 1 within its board. The names go
    as bound values: a quote or a percent sign stays as written."""
    statements = []
    positions: dict[str, int] = {}
    for board, code, name, kind, final, shown in COLUMNS:
        positions[board] = positions.get(board, 0) + 1
        statements.append(
            sa.text(SEED).bindparams(
                board=board,
                code=code,
                name=name,
                position=positions[board],
                kind=kind,
                is_final=final,
                is_visible=shown,
            )
        )
    return statements


def upgrade() -> None:
    for statement in TABLES:
        op.execute(statement)
    op.execute(LIVE)
    for seed in _seeds():
        op.execute(seed)


def downgrade() -> None:
    for table in (
        "survey_help_options",
        "board_card_events",
        "board_cards",
        "board_columns",
        "board_settings",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
