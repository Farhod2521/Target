"""Making room for a graphic whose band is already taken."""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Any, Final

from videokit import Zone
from videokit.components import component
from videokit.layout import zones_meet

from core.montage.dropped import DropReason

MAX_SHIFT_SECONDS: Final = 1.5
_EPS: Final = 1e-6


@dataclass(frozen=True, slots=True)
class Want:
    """A graphic and the stretch it asks for, on the finished video's clock."""

    name: str
    zone: Zone
    start: float
    length: float
    props: dict[str, Any]
    beats: dict[str, float | list[float]] = field(default_factory=dict)
    anchor_word: int | None = None
    said: float = 0.0

    @property
    def end(self) -> float:
        return self.start + self.length


@dataclass(frozen=True, slots=True)
class Fitted:
    """The newcomer where it fits (None when it does not), what is already
    placed after making room for it, and why it was left out."""

    want: Want | None
    kept: list[Want]
    reason: DropReason | None = None


def fit(want: Want, kept: list[Want], *, limit: float) -> Fitted:
    """``want`` placed among ``kept``, moved or with a panel shortened if
    it has to be; left out when neither makes room."""
    shortest = component(want.name).min_seconds
    for start in _starts(want, kept, limit=limit):
        end = min(start + want.length, limit)
        if end - start >= shortest - _EPS and not blockers(want.zone, start, end, kept):
            return Fitted(replace(want, start=start, length=end - start), kept)
    end = min(want.end, limit)
    if end - want.start < shortest - _EPS:
        return Fitted(None, kept, "end_card")
    if _is_panel(want.name):
        trimmed = _free_part(want, kept, end=end)
        if trimmed is not None:
            return Fitted(trimmed, kept)
    made = _panels_shortened(want, kept, end=end)
    if made is not None:
        return Fitted(replace(want, length=end - want.start), made)
    return Fitted(None, kept, "collision")


def blockers(zone: Zone, start: float, end: float, kept: Sequence[Want]) -> list[Want]:
    """What already holds a band ``zone`` shares, while ``[start, end)``."""
    return [
        other
        for other in kept
        if component(other.name).layer == "front"
        and zones_meet(zone, other.zone)
        and start < other.end - _EPS
        and other.start < end - _EPS
    ]


def _starts(want: Want, kept: Sequence[Want], *, limit: float) -> list[float]:
    """Where ``want`` may start: as asked, then right after or right before
    each graphic in its band, within the shift allowed, nearest first."""
    low = max(want.start - MAX_SHIFT_SECONDS, 0.0)
    high = min(want.start + MAX_SHIFT_SECONDS, limit)
    shared = [k for k in kept if zones_meet(want.zone, k.zone)]
    found = {want.start, limit - want.length, limit - component(want.name).min_seconds}
    found |= {k.end for k in shared} | {k.start - want.length for k in shared}
    return sorted(
        (at for at in found if low - _EPS <= at <= high + _EPS),
        key=lambda at: (round(abs(at - want.start), 6), at < want.start),
    )


def _free_part(want: Want, kept: Sequence[Want], *, end: float) -> Want | None:
    """``want`` held to the longest free part of its own stretch, if that
    is still as long as it may be at the least."""
    edges = sorted(
        {want.start, end}
        | {
            at
            for other in blockers(want.zone, want.start, end, kept)
            for at in (other.start, other.end)
            if want.start < at < end
        }
    )
    free = [
        (low, high)
        for low, high in pairwise(edges)
        if not blockers(want.zone, low, high, kept)
    ]
    if not free:
        return None
    low, high = max(free, key=lambda span: (span[1] - span[0], -span[0]))
    if high - low < component(want.name).min_seconds - _EPS:
        return None
    return replace(want, start=low, length=high - low)


def _panels_shortened(want: Want, kept: list[Want], *, end: float) -> list[Want] | None:
    """``kept`` with each panel in ``want``'s way shortened to clear it -
    or None if anything else is in the way, or a panel would get too short."""
    out = list(kept)
    for other in blockers(want.zone, want.start, end, kept):
        if not _is_panel(other.name) or other.anchor_word is None:
            return None
        if other.start < want.start:
            cut = replace(other, length=want.start - other.start)
        else:
            cut = replace(other, start=end, length=other.end - end)
        if cut.length < component(other.name).min_seconds - _EPS:
            return None
        out[out.index(other)] = cut
    return out


def _is_panel(name: str) -> bool:
    """A graphic that brings its own layout: the footage moves for it."""
    return component(name).layout is not None
