"""The window against the same length of time just before it, in words.

"Is it getting worse?" is one of the questions owners ask most, and the
context answered it with one period: thirty days of spend and results and
nothing to hold them against. The model would then either refuse or work
out a percentage of its own - and a percentage worked out by the model is
a figure no context supplied, which the gate removes from the answer.

So the movement is worked out here, once, the way the dashboard's arrows
are - see :func:`core.metrics.movement` - and handed over as text the answer
may quote. **Each kind of result against itself**: conversations last
month against leads this month is no movement at all.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from core.chat.rungs import RESULT_NAMES
from core.metrics import MIN_WEEK_LEADS, movement, noise_pct


@dataclass(frozen=True, slots=True)
class KindTotal:
    """One kind of result over one period: how many, and the money behind it."""

    kind: str
    count: int
    spend_minor: int


def moves(
    *,
    spend_now: int,
    spend_before: int,
    now: Sequence[KindTotal],
    before: Sequence[KindTotal],
) -> tuple[str, ...]:
    """``("spend up 12%", "leads down 20%", ...)``, flat figures left out.

    Empty when the earlier period spent nothing: an account that started
    this month did not improve, it started, and the answer should say there
    is nothing to compare with rather than read a movement out of nought.
    """
    if spend_before <= 0:
        return ()
    lines = [_said("spend", spend_now, spend_before, lower_is_better=None)]
    earlier = {item.kind: item for item in before}
    for item in now:
        was = earlier.get(item.kind)
        if was is None or was.count <= 0:
            continue
        name = RESULT_NAMES.get(item.kind, item.kind)
        counts = (item.count, was.count)
        lines.append(
            _said(name, item.count, was.count, lower_is_better=False, counts=counts)
        )
        if item.count > 0:
            lines.append(
                _said(
                    "cost per 1000 shown"
                    if item.kind == "view"
                    else f"cost of one of the {name}",
                    item.spend_minor / item.count,
                    was.spend_minor / was.count,
                    lower_is_better=True,
                    counts=counts,
                )
            )
    # A kind bought last period and not at all this one is the loudest
    # movement there is, and the loop above never meets it.
    current = {item.kind for item in now}
    for was in before:
        if was.kind not in current and was.count > 0:
            name = RESULT_NAMES.get(was.kind, was.kind)
            lines.append(
                _said(name, 0, was.count, lower_is_better=False, counts=(0, was.count))
            )
    return tuple(line for line in lines if line)


def _said(
    name: str,
    now: float,
    before: float,
    *,
    lower_is_better: bool | None,
    counts: tuple[int, int] = (0, 0),
) -> str:
    """One movement as a phrase, or ``""`` when it did not move.

    ``lower_is_better`` is ``None`` for spend, which is neither: more money
    out is the owner's choice, not news about the advertising.

    ``counts`` are the results behind it, now and before. A movement those
    counts are too small to carry is said as "within chance" rather than
    better or worse - see :func:`_beyond_chance`.
    """
    move = movement(now=now, before=before, lower_is_better=bool(lower_is_better))
    if move.direction == "flat":
        return ""
    phrase = f"{name} {move.direction} {move.percent}%"
    if lower_is_better is None:
        return phrase
    if not _beyond_chance(move.percent, *counts):
        return f"{phrase} (within chance)"
    return f"{phrase} ({'better' if move.is_good else 'worse'})"


def _beyond_chance(percent: int, now: int, before: int) -> bool:
    """Whether a movement is larger than counting error on these counts.

    The error bar alone, without the weekly report's floor of five: forty
    leads falling to two is real however few the two are, and two falling
    to one is not. A kind that stopped after enough of them is news
    whatever the arithmetic - nought has no error bar to compare with.
    """
    if now == 0:
        return before >= MIN_WEEK_LEADS
    bar = noise_pct(now=now, before=before)
    return bar is not None and percent > bar


__all__ = ["KindTotal", "moves"]
