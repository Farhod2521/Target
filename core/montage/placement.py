"""Components placed in time, once the cuts are final.

A planner ties each component to words (``anchor_word``, ``until_word``):
the numbers in the transcript it was shown. Seconds are worked out here,
after :mod:`core.montage.settle` has moved, joined and dropped stretches -
so a component lands on its words whatever the cut did to them.

**A word that was cut out** gives way to the nearest word that stayed,
counting by position in the transcript (the later one on a tie).

**Lengths** are held to the component's own limits from its manifest.

**Collisions.** Two components may not share a band of the frame at the
same moment. Placed in a fixed order - the closing ones first, then the
hook, then the rest by when they start - a newcomer that would collide
is moved, or a panel shortened, to make room (:mod:`core.montage.fitting`);
failing both, it is left out. The same input always gives the same video.

**The close comes after the words.** The end card and its button play
for :data:`END_SECONDS` after the last word kept, over footage that
carries on silently (``Placed.tail``): nothing said is ever covered, and a
graphic may stay up until the last word.

**Always there, whatever the plan said:** the end card with the
call-to-action button on it, a headline from the very first frame - the
planner's, or the first sentence said - and the name bar: when the
planner placed none, it goes in the first free stretch of
:data:`NAME_BAR_WINDOW`, after everything the planner asked for. The
opening headline stays until its sentence ends, up to
:data:`core.montage.opening.HOOK_MAX_SECONDS` - longer than its manifest
allows elsewhere.

**Never the same twice in a row.** A graphic that follows one of its own
kind is left out (decorations aside).

**Nothing empty.** A component there to show the brand (a name bar, the
end card) is left out when the brand has none of what it shows - an
account with no page has no name, and an empty box looks broken.

Every graphic asked for and left out is in ``Placed.dropped``, with why.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from videokit import Brand, ComponentUse, Cut, LayoutSpan
from videokit.components import component

from core.montage.captions import SpokenWord
from core.montage.dropped import Dropped, DropReason
from core.montage.fitting import Want, blockers, fit
from core.montage.opening import auto_hook, first_hook, opening_hook
from core.montage.word_clock import beat_times, nearest_kept, word_times

# How long the closing card plays, after the last word.
END_SECONDS: Final = 3.0
# The button comes a beat after the card.
CTA_DELAY: Final = 0.3
# How long the last beat of a component stays on screen before it leaves.
BEAT_HOLD_SECONDS: Final = 1.2
# A planner's button this close to the end gives way to the closing one.
LATE_BUTTON_SECONDS: Final = 8.0
# Where the name bar goes when the planner left it out: early, after the
# headline, while the viewer is still deciding whose video this is.
NAME_BAR_WINDOW: Final = (3.0, 7.0)
_NAME_BAR_STEP: Final = 0.25


@dataclass(frozen=True, slots=True)
class Placed:
    """Components with their seconds, where the footage moves for them,
    how long the video runs on after its last word (``tail``), what was
    asked for and left out, and the word each planned graphic is on
    (``anchors``: name, start, word)."""

    components: tuple[ComponentUse, ...]
    layouts: tuple[LayoutSpan, ...]
    tail: float = 0.0
    dropped: tuple[Dropped, ...] = ()
    anchors: tuple[tuple[str, float, int], ...] = ()


def closing_seconds(brand: Brand) -> float:
    """How long the video runs on after its last word: the closing card's
    time, when there is a card or a button to show; else none."""
    has_card = component("end_card").drawable(brand)
    return END_SECONDS if has_card or brand.cta_label else 0.0


def place(
    *,
    events: Sequence[Any],
    words: tuple[SpokenWord, ...],
    cuts: Sequence[Cut],
    brand: Brand,
) -> Placed:
    """Every component the video will show, at its seconds."""
    # Where the words end; the close plays after it, and nothing runs into it.
    limit = round(sum(cut.end - cut.start for cut in cuts), 3)
    times = word_times(words, cuts)
    dropped: list[Dropped] = []
    asked = _asked(events, times, len(words), brand=brand, length=limit, out=dropped)
    opening = first_hook(asked)
    hooks = [opening] if opening else auto_hook(words, times)
    hooks = [opening_hook(hook) for hook in hooks[:1]]
    # Decorations go last: they make way for everything with words.
    rest = sorted(
        (w for w in asked if w is not opening),
        key=lambda w: (component(w.name).layer == "decor", w.start, w.name),
    )
    kept: list[Want] = _closing(limit, brand)
    last = ""
    for want in [*hooks, *rest]:
        decor = component(want.name).layer == "decor"
        # The same graphic twice in a row reads as a mistake, not a rhythm.
        reason: DropReason | None = None
        if _used_up(want, kept):
            reason = "max_uses"
        elif want.name == last and not decor:
            reason = "same_twice"
        else:
            fitted = fit(want, kept, limit=limit)
            kept, reason = fitted.kept, fitted.reason
            if fitted.want is not None:
                kept.append(fitted.want)
                last = last if decor else want.name
        if reason is not None:
            dropped.append(_dropped(want, reason))
    if not any(w.name == "lower_third" for w in kept):
        kept += _name_bar(kept, brand=brand, limit=limit)
    kept += _progress(limit)
    kept.sort(key=lambda w: (w.start, w.name))
    return _placed(kept, tail=closing_seconds(brand), dropped=dropped)


def _placed(kept: list[Want], *, tail: float, dropped: list[Dropped]) -> Placed:
    return Placed(
        components=tuple(
            ComponentUse(
                name=w.name,
                zone=w.zone,
                start=round(w.start, 3),
                length=round(w.length, 3),
                props=w.props,
                beats=w.beats,
            )
            for w in kept
        ),
        layouts=tuple(
            LayoutSpan(start=round(w.start, 3), end=round(w.end, 3), layout=layout)
            for w in kept
            if (layout := component(w.name).layout) is not None
        ),
        tail=tail,
        dropped=tuple(sorted(dropped, key=lambda d: (d.at, d.component))),
        anchors=tuple(
            (w.name, round(w.start, 3), w.anchor_word)
            for w in kept
            if w.anchor_word is not None
        ),
    )


def _asked(
    events: Sequence[Any],
    times: dict[int, tuple[float, float]],
    count: int,
    *,
    brand: Brand,
    length: float,
    out: list[Dropped],
) -> list[Want]:
    """The planner's graphics on the clock; the ones that cannot be shown
    at all go to ``out``."""
    asked = []
    for event in events:
        want = _wanted(event, times, count)
        if want is None:
            out.append(Dropped(event.component, event.anchor_word, 0.0, "word_cut"))
        elif not component(want.name).drawable(brand):
            out.append(_dropped(want, "no_brand"))
        elif _second_close(want, length):
            out.append(_dropped(want, "late_cta"))
        else:
            asked.append(want)
    return asked


def _dropped(want: Want, reason: DropReason) -> Dropped:
    return Dropped(want.name, want.anchor_word, want.start, reason)


def _wanted(
    event: Any, times: dict[int, tuple[float, float]], count: int
) -> Want | None:
    first = nearest_kept(event.anchor_word, times, count)
    last = nearest_kept(event.until_word, times, count)
    if first is None or last is None:
        return None
    item = component(event.component)
    start = times[first][0]
    said = max(times[last][1] - start, 0.0)
    beats = beat_times(getattr(event, "beats", None), times, count)
    # Long enough for the last moment inside it to be seen, not to land
    # as it leaves.
    landed = max(
        (at for v in beats.values() for at in (v if isinstance(v, list) else [v])),
        default=start,
    )
    seen = max(said, landed - start + BEAT_HOLD_SECONDS)
    return Want(
        name=item.name,
        zone=event.zone,
        start=start,
        length=min(max(seen, item.min_seconds), item.max_seconds),
        props=event.props.model_dump(exclude_none=True),
        beats=beats,
        anchor_word=event.anchor_word,
        said=seen,
    )


def _second_close(want: Want, length: float) -> bool:
    """A planner's button in the last seconds, where the closing button is
    about to come anyway: two calls to action in a row read as one too many."""
    return want.name == "cta_button" and want.start >= length - LATE_BUTTON_SECONDS


def _used_up(want: Want, kept: list[Want]) -> bool:
    """Whether the video already shows ``want``'s component as often as it may."""
    most = component(want.name).max_uses
    return most is not None and sum(k.name == want.name for k in kept) >= most


def _progress(limit: float) -> list[Want]:
    """A thin line along the bottom edge filling up until the end card."""
    return [Want("progress_bar", "EDGE", 0.0, limit, {})] if limit >= 1.0 else []


def _closing(length: float, brand: Brand) -> list[Want]:
    """The end card and the button over it, after the last word; with no
    card, the ordinary button alone over the footage."""
    out = []
    card = component("end_card").drawable(brand)
    if card:
        out.append(Want("end_card", "FULL", length, END_SECONDS, {}))
    if brand.cta_label:
        name, zone = ("end_cta", "FULL") if card else ("cta_button", "LOWER_THIRD")
        out.append(Want(name, zone, length + CTA_DELAY, END_SECONDS - CTA_DELAY, {}))
    return out


def _name_bar(kept: list[Want], *, brand: Brand, limit: float) -> list[Want]:
    """The name bar in the first stretch of :data:`NAME_BAR_WINDOW` where
    its band is free, as long as it may stay; none if nowhere fits."""
    item = component("lower_third")
    if not item.drawable(brand):
        return []
    low, high = NAME_BAR_WINDOW
    high = min(high, limit)
    start = low
    while start + item.min_seconds <= high + 1e-6:
        end = min(start + item.max_seconds, high)
        if not blockers("LOWER_THIRD", start, end, kept):
            return [Want("lower_third", "LOWER_THIRD", start, end - start, {})]
        start += _NAME_BAR_STEP
    return []
