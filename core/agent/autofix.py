"""What the agent may put right without asking, and what it may never."""

from dataclasses import dataclass
from typing import Final

PAGE_UNSUBSCRIBED: Final = "page_unsubscribed"
LEADS_RECOVERABLE: Final = "leads_recoverable"


@dataclass(frozen=True, slots=True)
class Fix:
    """One repair, with the three conditions declared rather than assumed."""

    trigger: str
    action: str
    spends: bool
    decides: bool
    undo: str = ""


def allowed(fix: Fix) -> bool:
    """The gate. All three, or the answer is no."""
    return not fix.spends and not fix.decides and reversible(fix)


def reversible(fix: Fix) -> bool:
    """Whether this repair can be put back."""
    return bool(fix.undo) or not fix.decides


_ALLOWED: Final[dict[str, Fix]] = {
    PAGE_UNSUBSCRIBED: Fix(
        trigger=PAGE_UNSUBSCRIBED,
        action="relink_page",
        spends=False,
        decides=False,
    ),
    LEADS_RECOVERABLE: Fix(
        trigger=LEADS_RECOVERABLE,
        action="recover_leads",
        spends=False,
        decides=False,
    ),
}


def fix_for(trigger: str) -> Fix | None:
    """The repair for one trigger, if it is one the agent may make."""
    found = _ALLOWED.get(trigger.strip()) if trigger else None
    if found is None or not allowed(found):
        return None
    return found


def triggers() -> tuple[str, ...]:
    """Every trigger the agent may act on, sorted. For the layer above."""
    return tuple(sorted(_ALLOWED))


__all__ = [
    "LEADS_RECOVERABLE",
    "PAGE_UNSUBSCRIBED",
    "Fix",
    "allowed",
    "fix_for",
    "reversible",
    "triggers",
]
