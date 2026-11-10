"""Bring a customer's campaign copy up to date when the office reads it."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.common import throttle
from app.modules.ads.constants import AUTO_SYNC_COOLING_MINUTES
from app.modules.ads.services.mirror import queue_sync
from app.modules.backoffice.selectors.delivery import accounts_to_refresh
from app.modules.integrations.models import AdAccount

BUCKET = "office:ads-refresh"


def refresh_stale(db: Session, *, accounts: list[AdAccount], now: datetime) -> bool:
    """Queue a mirror sync for each stale account, once per cooling window.

    Ignores the owner's plan on purpose: the sweeps that read the plan are
    what left the copy behind, and the office asked to see the truth. The
    caller commits; the task is sent on commit.
    """
    queued = False
    for account in accounts_to_refresh(accounts, now=now):
        if throttle.hit(
            bucket=BUCKET,
            key=f"{account.provider}:{account.external_id}",
            limit=1,
            window_seconds=AUTO_SYNC_COOLING_MINUTES * 60,
        ):
            queue_sync(db, account)
            queued = True
    return queued
