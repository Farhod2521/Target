"""Whether a movement is larger than the noise underneath it."""

from math import sqrt

MIN_WEEK_LEADS = 5


def noise_pct(*, now: int, before: int) -> int | None:
    """How large a movement has to be before it is not the counting error."""
    if now <= 0 or before <= 0:
        return None
    return round(100 / sqrt(now) + 100 / sqrt(before))


def is_beyond_noise(
    *, percent: int, now: int, before: int, floor: int = MIN_WEEK_LEADS
) -> bool:
    """Whether a movement of ``percent`` is worth explaining."""
    if now < floor or before < floor:
        return False
    bar = noise_pct(now=now, before=before)
    return bar is not None and percent > bar
