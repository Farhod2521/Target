"""The Sales board's own figures: where a lead came from, and a staff
member's «no calls for me» switch.

``users.signup_via`` says how the account was opened (email, Google or
Telegram) and ``users.signup_utm`` the landing link's utm_* marks.
Accounts opened before: a Google or Telegram identity made within ten
minutes of the sign-up names that door, any other account is «email».
``phone_extensions.accepts_calls``: false, the routing passes the number
over and its browser phone turns a ring away. Additive and idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0066"
down_revision: str | Sequence[str] | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS signup_via varchar(16) "
        "NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS signup_utm jsonb "
        "NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE phone_extensions ADD COLUMN IF NOT EXISTS accepts_calls "
        "boolean NOT NULL DEFAULT true"
    )
    # Only rows not yet told: a rerun changes nothing.
    op.execute(
        """
        UPDATE users AS u SET signup_via = found.provider
        FROM (
            SELECT DISTINCT ON (s.owner_id) s.owner_id, s.provider
            FROM social_identities AS s
            JOIN users AS o ON o.id = s.owner_id
            WHERE s.provider IN ('google', 'telegram')
              AND s.created_at <= o.date_joined + interval '10 minutes'
            ORDER BY s.owner_id, s.created_at
        ) AS found
        WHERE u.id = found.owner_id AND u.signup_via = ''
        """
    )
    op.execute(
        "UPDATE users SET signup_via = 'email' "
        "WHERE signup_via = '' AND crm_owner_id IS NULL AND is_staff = false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE phone_extensions DROP COLUMN IF EXISTS accepts_calls")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS signup_utm")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS signup_via")
