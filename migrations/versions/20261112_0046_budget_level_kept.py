"""A launch made with its budget at the campaign says so.

Until now a launch nobody chose a budget level for kept its daily budget at
the campaign, and nothing was written down: the choice is stored only when
the owner touches «Byudjet». The default moves to the ad group, so a launch
already built the old way would be read as the new one: the office would
show the wrong level, and a second attempt at a half-built launch would
throw away the campaign Meta holds.

Each such launch gets ``budget_level: campaign`` in its answers. Which ones
they are is read from the mirror, not guessed: the launch's campaign holds a
daily budget of its own. A campaign made so lately that the mirror has not
seen it yet followed the old rule, which is repeated here: no groups stored,
so the campaign holds the money. Drafts with no campaign are left alone and
take the new default.

Idempotent: a launch that names its level is not touched.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEPT_AT_CAMPAIGN = """
UPDATE campaign_launches AS launch
SET answers = jsonb_set(launch.answers::jsonb, '{budget_level}', '"campaign"')
WHERE jsonb_typeof(launch.answers::jsonb) = 'object'
  AND coalesce(launch.answers::jsonb ->> 'budget_level', '') = ''
  AND EXISTS (
    SELECT 1
    FROM goal_campaigns AS shared
    LEFT JOIN campaigns AS mirrored
      ON mirrored.provider = shared.provider
     AND mirrored.external_id = shared.external_id
    WHERE shared.id = launch.goal_campaign_id
      AND shared.external_id <> ''
      AND (
        mirrored.daily_budget_minor IS NOT NULL
        OR (
          mirrored.id IS NULL
          AND shared.retired_at IS NULL
          AND jsonb_typeof(launch.ad_groups::jsonb) = 'array'
          AND jsonb_array_length(launch.ad_groups::jsonb) = 0
        )
      )
  )
"""


def upgrade() -> None:
    op.execute(KEPT_AT_CAMPAIGN)


def downgrade() -> None:
    # The level written here is what those campaigns hold; it stays true.
    pass
