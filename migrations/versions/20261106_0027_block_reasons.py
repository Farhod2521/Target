"""Block reasons, the blocks made with them, and the system's suggestions.

`block_reasons` is the super admin's list; the system's own reasons and the
catch-all «Boshqa» are seeded. Every account blocked today gets its open
block: the system's Facebook reason where the system blocked it, «Boshqa»
with the old words as the note otherwise, hidden from the account as it was.
Accounts refused for a reused Facebook account since they were last opened,
and still open, become suggestions. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS block_reasons (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        code varchar(32) UNIQUE,
        name varchar(80) NOT NULL,
        message_uz text NOT NULL DEFAULT '',
        message_ru text NOT NULL DEFAULT '',
        message_en text NOT NULL DEFAULT '',
        position integer NOT NULL DEFAULT 0,
        is_archived boolean NOT NULL DEFAULT false
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_blocks (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED,
        reason_id uuid NOT NULL REFERENCES block_reasons(id) ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED,
        shown_to_user boolean NOT NULL DEFAULT false,
        note text NOT NULL DEFAULT '',
        blocked_by_id uuid REFERENCES users(id) ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED,
        blocked_at timestamptz NOT NULL,
        lifted_at timestamptz,
        lifted_by_id uuid REFERENCES users(id) ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED,
        lift_note text NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS block_suggestions (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED,
        reason_id uuid NOT NULL REFERENCES block_reasons(id) ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED,
        detail jsonb NOT NULL DEFAULT '{}'::jsonb,
        times integer NOT NULL DEFAULT 1,
        last_at timestamptz NOT NULL,
        resolved_at timestamptz,
        resolved_by_id uuid REFERENCES users(id) ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED,
        resolution varchar(16) NOT NULL DEFAULT '',
        note text NOT NULL DEFAULT ''
    )
    """,
)
INDEXES = (
    "CREATE INDEX IF NOT EXISTS account_blocks_owner_blocked_idx "
    "ON account_blocks (owner_id, blocked_at DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS account_blocks_one_open "
    "ON account_blocks (owner_id) WHERE lifted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_account_blocks_reason_id "
    "ON account_blocks (reason_id)",
    "CREATE INDEX IF NOT EXISTS ix_account_blocks_blocked_by_id "
    "ON account_blocks (blocked_by_id)",
    "CREATE INDEX IF NOT EXISTS ix_account_blocks_lifted_by_id "
    "ON account_blocks (lifted_by_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS block_suggestions_one_open "
    "ON block_suggestions (owner_id, reason_id) WHERE resolved_at IS NULL",
    "CREATE INDEX IF NOT EXISTS block_suggestions_open_last "
    "ON block_suggestions (resolved_at, last_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_block_suggestions_owner_id "
    "ON block_suggestions (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_block_suggestions_reason_id "
    "ON block_suggestions (reason_id)",
    "CREATE INDEX IF NOT EXISTS ix_block_suggestions_resolved_by_id "
    "ON block_suggestions (resolved_by_id)",
)
SEED = """
    INSERT INTO block_reasons
        (id, created_at, updated_at, code, name, message_uz, message_ru,
         message_en, position)
    VALUES
        (gen_random_uuid(), now(), now(), 'meta_identity_reused',
         'Bitta Facebook bilan ikkinchi kabinet',
         'Bu Facebook akkaunt boshqa kabinetga ulangan. Bitta Facebook akkaunt bitta kabinetda ishlaydi.',
         'Этот аккаунт Facebook подключён к другому кабинету. Один аккаунт Facebook работает только в одном кабинете.',
         'This Facebook account is connected to another cabinet. One Facebook account works in one cabinet only.',
         0),
        (gen_random_uuid(), now(), now(), 'google_identity_reused',
         'Bitta Google bilan ikkinchi kabinet',
         'Bu Google akkaunt boshqa kabinetga ulangan. Bitta Google akkaunt bitta kabinetda ishlaydi.',
         'Этот аккаунт Google подключён к другому кабинету. Один аккаунт Google работает только в одном кабинете.',
         'This Google account is connected to another cabinet. One Google account works in one cabinet only.',
         0),
        (gen_random_uuid(), now(), now(), 'other', 'Boshqa', '', '', '', 3)
    ON CONFLICT (code) DO NOTHING
"""
# The last block event of each account blocked today names why; none at all
# (blocked before events) is «Boshqa» with no note. The visitors' chat
# account is shut by design, not blocked.
BLOCKS = """
    INSERT INTO account_blocks
        (id, created_at, updated_at, owner_id, reason_id, shown_to_user, note,
         blocked_by_id, blocked_at)
    SELECT gen_random_uuid(), now(), now(), u.id,
           COALESCE(
               (SELECT r.id FROM block_reasons r WHERE r.code = last.reason),
               (SELECT r.id FROM block_reasons r WHERE r.code = 'other')
           ),
           false,
           CASE WHEN last.reason = 'meta_identity_reused' THEN ''
                ELSE COALESCE(last.reason, '') END,
           (SELECT a.id FROM users a WHERE a.id::text = last.actor_id),
           COALESCE(last.occurred_at, u.date_joined)
    FROM users u
    LEFT JOIN LATERAL (
        SELECT e.payload->>'reason' AS reason,
               e.payload->>'actor_id' AS actor_id,
               e.occurred_at
        FROM events e
        WHERE e.owner_id = u.id AND e.name = 'user.blocked'
        ORDER BY e.occurred_at DESC
        LIMIT 1
    ) last ON true
    WHERE u.is_active = false
      AND u.crm_owner_id IS NULL
      AND u.email <> 'public-chat@targetolog.invalid'
      AND NOT EXISTS (
          SELECT 1 FROM account_blocks b
          WHERE b.owner_id = u.id AND b.lifted_at IS NULL
      )
"""
SUGGESTIONS = """
    INSERT INTO block_suggestions
        (id, created_at, updated_at, owner_id, reason_id, detail, times, last_at)
    SELECT gen_random_uuid(), min(e.occurred_at), now(), u.id,
           (SELECT r.id FROM block_reasons r WHERE r.code = 'meta_identity_reused'),
           jsonb_build_object(
               'external_user_id', (array_agg(e.payload->>'external_user_id'
                                    ORDER BY e.occurred_at DESC))[1],
               'held_by', (array_agg(e.payload->>'held_by'
                           ORDER BY e.occurred_at DESC))[1]
           ),
           count(*), max(e.occurred_at)
    FROM users u
    JOIN events e ON e.owner_id = u.id AND e.name = 'connection.refused_duplicate'
    WHERE u.is_active = true
      AND u.is_staff = false
      AND e.occurred_at > COALESCE(
          (SELECT max(o.occurred_at) FROM events o
           WHERE o.owner_id = u.id AND o.name = 'user.unblocked'),
          '-infinity'::timestamptz
      )
      AND NOT EXISTS (
          SELECT 1 FROM block_suggestions s
          WHERE s.owner_id = u.id AND s.resolved_at IS NULL
      )
    GROUP BY u.id
"""


def upgrade() -> None:
    for statement in TABLES:
        op.execute(statement)
    for statement in INDEXES:
        op.execute(statement)
    op.execute(SEED)
    op.execute(BLOCKS)
    op.execute(SUGGESTIONS)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS block_suggestions")
    op.execute("DROP TABLE IF EXISTS account_blocks")
    op.execute("DROP TABLE IF EXISTS block_reasons")
