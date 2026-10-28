"""«Keyinroq»: the survey waits, on every screen, without a row written."""

from app.common.cache import cache
from app.modules.accounts.models import User
from app.modules.surveys.constants import SNOOZE_KEY, SNOOZE_SECONDS


def snooze_survey(*, user: User) -> None:
    """Hold the survey back for a while. Kept in the cache, shared by the
    cabinet, the mini app and the bot."""
    cache.set(SNOOZE_KEY.format(user_id=user.id), True, SNOOZE_SECONDS)
