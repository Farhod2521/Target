"""What a screen must say over a campaign's own word: it is only a copy.

Three things make «Ishlayapti» untrue while the copy still says it:

* frozen - the account hangs on a connection that no longer works;
* stale - nothing has read the campaign for longer than its sweep allows (an
  owner whose plan ended long ago, a read the network keeps refusing): three
  hours on the account the cabinet advertises on, read every half hour, and
  thirty on one it only watches, read once a night;
* account stopped - the network switched the account off and left the
  campaign on.

One rule for the list, the campaign's page and the Expert table, so no
screen says more than another knows.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.constants import NOT_RUNNING, SYNC_STALE_MINUTES
from app.modules.integrations.selectors import frozen_accounts
from app.modules.integrations.selectors.demo import is_demo_account
from app.modules.integrations.selectors.standing import StoppedKind, stopped_kind

STALE_AFTER: Final = timedelta(minutes=SYNC_STALE_MINUTES)
# An account that is only watched (not the one the cabinet advertises on) is
# read once a night, by its own clock: a day and a margin is its allowance,
# or every row of it would be called old from morning to night.
WATCHED_STALE_AFTER: Final = timedelta(hours=30)


@dataclass(frozen=True, slots=True)
class Marks:
    frozen_since: str | None = None
    """ISO, or "" when never read; ``None`` on a row that is being read."""
    stale_since: str | None = None
    account_stopped: StoppedKind | None = None

    def out(self) -> dict[str, Any]:
        return {
            "frozen_since": self.frozen_since,
            "stale_since": self.stale_since,
            "account_stopped": self.account_stopped,
        }


NONE: Final = Marks()


def campaign_marks(
    db: Session, *, campaigns: Iterable[Any], now: datetime | None = None
) -> dict[str, Marks]:
    """Each campaign's marks, by its external id."""
    rows = list(campaigns)
    now = now or utcnow()
    frozen = frozen_accounts(db, account_ids={row.ad_account_id for row in rows})
    found: dict[str, Marks] = {}
    for row in rows:
        frozen_since: str | None = None
        if row.ad_account_id in frozen:
            stamp = frozen[row.ad_account_id]
            frozen_since = stamp.isoformat() if stamp else ""
        found[str(row.external_id)] = Marks(
            frozen_since=frozen_since,
            stale_since=None if frozen_since is not None else _stale(row, now=now),
            account_stopped=stopped_kind(row.ad_account),
        )
    return found


def _stale(row: Any, *, now: datetime) -> str | None:
    """A switched-off or finished campaign does not go stale: its word holds."""
    if str(row.delivery) in NOT_RUNNING or row.synced_at is None:
        return None
    # The showcase is never read: nothing stands behind it to go old.
    if is_demo_account(row.ad_account):
        return None
    watched = not getattr(row.ad_account, "is_active", True)
    if now - row.synced_at <= (WATCHED_STALE_AFTER if watched else STALE_AFTER):
        return None
    return str(row.synced_at.isoformat())


__all__ = ["NONE", "STALE_AFTER", "Marks", "campaign_marks"]
