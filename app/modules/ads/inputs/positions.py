"""What is wrong with the positions an owner ticked, in the owner's words.

One wording for the launch editor and for the edit of a running advert.
"""

from typing import Final

from app.modules.ads.constants import PLACEMENT_POSITION_LABELS
from core.targeting.placements import POSITION_NEEDS, positions_fault

NOTHING_TICKED: Final = "Kamida bitta joy tanlang."
NOT_OFFERED: Final = "Ro'yxatdan tanlang."


def positions_problem(sent: object, *, mode: str) -> str:
    """The sentence for the first fault in these ticks; empty when they can run."""
    fault = positions_fault(sent, mode=mode)
    if fault is None:
        return ""
    kind, lonely = fault
    if kind == "empty":
        return NOTHING_TICKED
    if lonely is None:
        return NOT_OFFERED
    app, item = lonely
    needed = " yoki ".join(
        f"«{PLACEMENT_POSITION_LABELS[other][position]}»"
        for other, position in POSITION_NEEDS[lonely]
    )
    return (
        f"«{PLACEMENT_POSITION_LABELS[app][item]}» yolg'iz ishlamaydi: "
        f"{needed} ham tanlang."
    )


__all__ = ["NOTHING_TICKED", "NOT_OFFERED", "positions_problem"]
