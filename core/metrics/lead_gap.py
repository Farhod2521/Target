"""Whether the provider counted leads that never reached this product."""

from typing import Final

SCREEN_GAP_PCT: Final = 10
SCREEN_GAP_MISSING: Final = 2

ALARM_GAP_PCT: Final = 20
ALARM_GAP_MISSING: Final = 3


def missing_leads(*, reported: int, ours: int, share_pct: int, at_least: int) -> int:
    """How many of the provider's leads are not here, when that is a gap."""
    missing = reported - ours
    if missing < at_least or missing * 100 < share_pct * reported:
        return 0
    return missing


__all__ = [
    "ALARM_GAP_MISSING",
    "ALARM_GAP_PCT",
    "SCREEN_GAP_MISSING",
    "SCREEN_GAP_PCT",
    "missing_leads",
]
