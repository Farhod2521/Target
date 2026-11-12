"""Which queue a task goes to when the account it works on decides it.

Google answers slower than Meta, and a large account's read can take a
minute. On the queues they shared, two such reads held both of the sync
worker's slots and every Meta account waited behind them; a slow change at
Google held a slot a Meta owner's press was waiting for. So Google's work
has queues of its own, kept apart the way the rest are:

- ``google``: what somebody is waiting on - the wizard, a press.
- ``google_sync``: reading accounts in the background.

The tasks below carry no ``queue=`` of their own, because Celery lets the
decorator's queue win over this router; here every one of them is given
one. A ``queue=`` passed to ``apply_async`` still wins over both.

**Never in the way of a send.** The provider is looked up in the database;
if that fails, the task goes where it always went, as it did before this
module existed.
"""

import logging
import uuid
from functools import lru_cache
from typing import Any, Final

logger = logging.getLogger(__name__)

GOOGLE_QUEUE: Final = "google"
GOOGLE_SYNC_QUEUE: Final = "google_sync"
# Meta's figures apart from its mirror: measured on production, 2026-11-12,
# the two shared two slots that were 87 percent busy, and a task waited ten
# minutes on average. Each now waits only behind its own kind.
FIGURES_QUEUE: Final = "figures"
_GOOGLE: Final = "google"

# Task name -> (the queue it had, the queue a Google account's run takes).
_BY_ACCOUNT: Final[dict[str, tuple[str, str]]] = {
    "app.modules.ads.tasks.sync_ad_account_task": ("sync", GOOGLE_SYNC_QUEUE),
    "app.modules.metrics.tasks.sync_insights_task": (FIGURES_QUEUE, GOOGLE_SYNC_QUEUE),
    "app.modules.metrics.tasks.sync_today_task": (FIGURES_QUEUE, GOOGLE_SYNC_QUEUE),
    "app.modules.metrics.tasks.refill_history_task": (FIGURES_QUEUE, GOOGLE_SYNC_QUEUE),
    "app.modules.metrics.tasks.sync_observed_task": (FIGURES_QUEUE, GOOGLE_SYNC_QUEUE),
}
_BY_CHANGE: Final[dict[str, tuple[str, str]]] = {
    "app.modules.ads.tasks.apply_change_task": ("agent", GOOGLE_QUEUE),
    "app.modules.ads.tasks.apply_delete_task": ("agent", GOOGLE_QUEUE),
    "app.modules.ads.tasks.apply_swap_task": ("agent", GOOGLE_QUEUE),
}

ROUTED: Final = frozenset(_BY_ACCOUNT) | frozenset(_BY_CHANGE)


def route_task(
    name: str,
    args: Any,
    kwargs: Any,
    options: Any,
    task: Any = None,
    **_: Any,
) -> dict[str, str] | None:
    """Celery's ``task_routes`` hook: a queue for the tasks above, else nothing."""
    if name in _BY_ACCOUNT:
        usual, google = _BY_ACCOUNT[name]
        found = _first(args, kwargs, "ad_account_id")
        return {
            "queue": google if _provider(account_provider, found) == _GOOGLE else usual
        }
    if name in _BY_CHANGE:
        usual, google = _BY_CHANGE[name]
        found = _first(args, kwargs, "log_id")
        return {
            "queue": google if _provider(change_provider, found) == _GOOGLE else usual
        }
    return None


def _first(args: Any, kwargs: Any, name: str) -> str:
    if args:
        return str(args[0])
    return str((kwargs or {}).get(name) or "")


def _provider(lookup: Any, key: str) -> str:
    try:
        pk = uuid.UUID(key)
    except ValueError:
        return ""
    try:
        return str(lookup(pk))
    except Exception:
        logger.warning(
            "queue of %s not decided; it goes the usual way", key, exc_info=True
        )
        return ""


@lru_cache(maxsize=4096)
def account_provider(pk: uuid.UUID) -> str:
    """An account's provider; it never changes, so it is asked once a process."""
    from sqlalchemy import select

    from app.common.db import SessionLocal
    from app.modules.integrations.models import AdAccount

    with SessionLocal() as db:
        return db.scalar(select(AdAccount.provider).where(AdAccount.id == pk)) or ""


def change_provider(pk: uuid.UUID) -> str:
    from sqlalchemy import select

    from app.common.db import SessionLocal
    from app.modules.audit.models import ActionLog

    with SessionLocal() as db:
        return (
            db.scalar(select(ActionLog.target_provider).where(ActionLog.id == pk)) or ""
        )


__all__ = ["FIGURES_QUEUE", "GOOGLE_QUEUE", "GOOGLE_SYNC_QUEUE", "ROUTED", "route_task"]
