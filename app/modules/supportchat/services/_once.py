"""One press of Send, one message.

Each drawing of a composer carries a fresh ``send_key``. The first write to
arrive with it claims it; another with the same key is
:class:`AlreadySent` and writes nothing. A write that fails gives its key
back, so the corrected retry is not mistaken for a repeat. The claim lives
in the cache: a guard against a burst, not a record.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from app.common.cache import cache
from app.modules.accounts.models import User
from app.modules.supportchat.exceptions import AlreadySent

logger = logging.getLogger(__name__)

KEY: Final = "supportchat:send:{sender}:{key}"
# Longer than the slowest upload takes to arrive.
CLAIM_SECONDS: Final = 30 * 60


@contextmanager
def once(*, sender: User, key: str) -> Iterator[None]:
    """Run the write inside only for the first arrival of this key. No key
    is no guard."""
    if not key:
        yield
        return
    name = KEY.format(sender=sender.id, key=key)
    if not _claim(name):
        raise AlreadySent
    stored = False
    try:
        yield
        stored = True
    finally:
        if not stored:
            _release(name)


def _claim(name: str) -> bool:
    try:
        return bool(cache.add(name, "1", timeout=CLAIM_SECONDS))
    except Exception:
        # A lost guard costs a duplicate, a refusal would cost the message.
        logger.warning("support send guard unavailable, allowing through")
        return True


def _release(name: str) -> None:
    try:
        cache.delete(name)
    except Exception:
        logger.warning("support send guard could not release %s", name)
