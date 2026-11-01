"""When a survey runs, how long a customer waits for it, and who saw it.

`surveys`: an optional first and last moment, and the days on a plan before it
is asked; a survey already written keeps the week the product asks now.
`survey_sightings`: one row per customer who was shown a survey, so the office
can read how many saw it and put it off, not only how many answered.
Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE surveys ADD COLUMN IF NOT EXISTS starts_at timestamptz")
    op.execute("ALTER TABLE surveys ADD COLUMN IF NOT EXISTS ends_at timestamptz")
    op.execute(
        "ALTER TABLE surveys "
        "ADD COLUMN IF NOT EXISTS ask_after_days smallint NOT NULL DEFAULT 7"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS survey_sightings (
            id uuid PRIMARY KEY,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            survey_id uuid NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
            owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            later_count integer NOT NULL DEFAULT 0,
            CONSTRAINT uniq_survey_sighting UNIQUE (survey_id, owner_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS survey_sightings_owner_idx "
        "ON survey_sightings (owner_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS survey_sightings")
    op.execute("ALTER TABLE surveys DROP COLUMN IF EXISTS ask_after_days")
    op.execute("ALTER TABLE surveys DROP COLUMN IF EXISTS ends_at")
    op.execute("ALTER TABLE surveys DROP COLUMN IF EXISTS starts_at")
