"""Components placed in time, once the cuts are final."""

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

END_SECONDS: Final = 3.0
CTA_DELAY: Final = 0.3
BEAT_HOLD_SECONDS: Final = 1.2
LATE_BUTTON_SECONDS: Final = 8.0
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
    limit = round(sum(cut.end - cut.start for cut in cuts), 3)
    times = word_times(words, cuts)
    dropped: list[Dropped] = []
    asked = _asked(events, times, len(words), brand=brand, length=limit, out=dropped)
    opening = first_hook(asked)
    hooks = [opening] if opening else auto_hook(words, times)
    hooks = [opening_hook(hook) for hook in hooks[:1]]
    rest = sorted(
        (w for w in asked if w is not opening),
        key=lambda w: (component(w.name).layer == "decor", w.start, w.name),
    )
    kept: list[Want] = _closing(limit, brand)
    last = ""
    for want in [*hooks, *rest]:
        decor = component(want.name).layer == "decor"
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
