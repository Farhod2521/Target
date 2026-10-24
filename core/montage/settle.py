"""Claude's plan, made safe to render."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from videokit import Brand, ComponentUse, Cut, LayoutSpan, Overlay, Transition

from core.montage.captions import SpokenWord
from core.montage.dropped import Dropped
from core.montage.emphasis import punch_times
from core.montage.errors import NothingToKeepError
from core.montage.greetings import without_greeting
from core.montage.pauses import without_pauses
from core.montage.placement import closing_seconds, place
from core.montage.plan import MontagePlan, PlanSegment, PlanSegmentV3
from core.montage.rhythm import lively_punches

MIN_SEGMENT_SECONDS = 0.6
PAD_BEFORE_SECONDS = 0.08
PAD_AFTER_SECONDS = 0.18
SPEECH_EDGE_SECONDS = 0.05
_OVERLAP = -(PAD_BEFORE_SECONDS + PAD_AFTER_SECONDS) - 0.01
JOIN_GAP_SECONDS = 0.15
JUMP_WINDOW_SECONDS = 20.0
CLOSE_ZOOM = 1.15
MOST_CHANGES = 4
LENGTH_SLACK = 1.15


def speech_limits(target_seconds: float, *, tail: float) -> tuple[float, float]:
    """How long the words should run, and may run at most, in a video asked
    to be ``target_seconds`` long that runs on ``tail`` seconds after its
    last word (the closing card). The planner is told these and the cut
    is held to the second."""
    return (
        max(target_seconds - tail, 0.0),
        max(target_seconds * LENGTH_SLACK - tail, 0.0),
    )


@dataclass(frozen=True, slots=True)
class Settled:
    """What is rendered: stretches, text, and how long it runs."""

    cuts: tuple[Cut, ...]
    overlays: tuple[Overlay, ...]
    length: float


def settle(
    *,
    plan: MontagePlan,
    source_seconds: float,
    target_seconds: float,
    words: tuple[SpokenWord, ...],
) -> Settled:
    """The plan, held to the file, to whole words and to the asked length."""
    kept = kept_cuts(
        segments=plan.segments,
        source_seconds=source_seconds,
        target_seconds=target_seconds,
        words=words,
    )
    cuts = tuple(cut for cut, _segment in kept)
    length = round(sum(cut.end - cut.start for cut in cuts), 3)
    return Settled(cuts=cuts, overlays=_overlays(plan, length=length), length=length)


@dataclass(frozen=True, slots=True)
class SettledV3:
    """A v3 plan made safe: cuts, components on the clock, layouts, and the
    moments to punch in on."""

    cuts: tuple[Cut, ...]
    length: float
    components: tuple[ComponentUse, ...]
    layouts: tuple[LayoutSpan, ...]
    punches: tuple[float, ...]
    tail: float = 0.0
    dropped: tuple[Dropped, ...] = ()
    anchors: tuple[tuple[str, float, int], ...] = ()


def settle_v3(
    *,
    plan: Any,
    source_seconds: float,
    target_seconds: float,
    words: tuple[SpokenWord, ...],
    brand: Brand,
) -> SettledV3:
    """A v3 plan (see :func:`core.montage.plan.plan_schema`) made safe to render."""
    tail = closing_seconds(brand)
    kept: list[tuple[Cut, PlanSegmentV3]] = kept_cuts(
        segments=plan.segments,
        source_seconds=source_seconds,
        target_seconds=target_seconds,
        words=words,
        tail=tail,
    )
    enters = section_changes([segment for _, segment in kept])
    cuts = without_pauses(
        without_greeting(
            [
                cut.model_copy(update={"enter": enter})
                for (cut, _), enter in zip(kept, enters, strict=True)
            ],
            words,
        ),
        words,
    )
    placed = place(events=plan.events, words=words, cuts=cuts, brand=brand)
    return SettledV3(
        cuts=cuts,
        length=round(sum(cut.end - cut.start for cut in cuts) + placed.tail, 3),
        components=placed.components,
        layouts=placed.layouts,
        punches=lively_punches(
            punch_times(plan.emphasis, words=words, cuts=cuts),
            components=placed.components,
            cuts=cuts,
            words=words,
        ),
        tail=placed.tail,
        dropped=placed.dropped,
        anchors=placed.anchors,
    )


def section_changes(segments: Sequence[PlanSegmentV3]) -> list[Transition]:
    """How each kept stretch comes in: as the plan said, and where it moves
    on to a new part (its role changes) with none said, a burst - at most
    :data:`MOST_CHANGES` changes in all. The first opens plainly."""
    out: list[Transition] = []
    for index, segment in enumerate(segments):
        enter = segment.transition_in
        if index == 0:
            enter = "none"
        elif enter == "none" and segment.role != segments[index - 1].role:
            enter = "burst"
        if enter != "none" and sum(e != "none" for e in out) >= MOST_CHANGES:
            enter = "none"
        out.append(enter)
    return out


def kept_cuts[S: PlanSegment](
    *,
    segments: Sequence[S],
    source_seconds: float,
    target_seconds: float,
    words: tuple[SpokenWord, ...],
    tail: float = 0.0,
) -> list[tuple[Cut, S]]:
    """Each cut that survives, with the segment that opened it; together
    no longer than the words may run (:func:`speech_limits`)."""
    _target, ceiling = speech_limits(target_seconds, tail=tail)
    kept: list[tuple[Cut, S]] = []
    total = 0.0
    asked_end = -1.0
    for segment in segments:
        cuts = [cut for cut, _ in kept]
        start = _snap_start(max(segment.start, 0.0), words)
        end = _snap_end(min(segment.end, source_seconds), words, source_seconds)
        start, end = _padded(start, end, words, source_seconds)
        meets = bool(cuts) and (
            _follows(cuts[-1], start, end)
            or (_meets(asked_end, segment) and end > cuts[-1].end)
        )
        if meets:
            start = cuts[-1].end
        joins = meets and _same_shot(kept[-1][1], segment)
        if end - start < MIN_SEGMENT_SECONDS and not joins:
            continue
        if not meets and _overlaps(cuts, start, end):
            continue
        if total + (end - start) > ceiling:
            end = _snap_end(start + ceiling - total, words, source_seconds, back=True)
            if end - start < MIN_SEGMENT_SECONDS:
                break
        total += end - start
        asked_end = segment.end
        if joins:
            last, opened = kept[-1]
            kept[-1] = (last.model_copy(update={"end": round(end, 3)}), opened)
            continue
        zoom = CLOSE_ZOOM if segment.framing == "close" else 1.0
        kept.append((Cut(start=round(start, 3), end=round(end, 3), zoom=zoom), segment))
    if not kept:
        raise NothingToKeepError("no stretch of the source survived the checks")
    unjumped = _unjumped([cut for cut, _ in kept])
    return [(cut, segment) for cut, (_, segment) in zip(unjumped, kept, strict=True)]


def _overlays(plan: MontagePlan, *, length: float) -> tuple[Overlay, ...]:
    kept: list[Overlay] = []
    for item in plan.texts:
        if item.at >= length:
            continue
        seconds = min(item.seconds, length - item.at)
        if seconds < MIN_SEGMENT_SECONDS:
            continue
        kept.append(
            Overlay(
                text=item.text.strip(),
                start=round(item.at, 3),
                length=round(seconds, 3),
                position=item.place,
            )
        )
    return tuple(kept)


def _snap_start(at: float, words: tuple[SpokenWord, ...]) -> float:
    """Back to the start of a word the moment falls inside."""
    for word in words:
        if word.start < at < word.end:
            return word.start
    return at


def _snap_end(
    at: float,
    words: tuple[SpokenWord, ...],
    limit: float,
    *,
    back: bool = False,
) -> float:
    """On to the end of a word the moment falls inside - or back to its start
    when the length is what is being cut."""
    for word in words:
        if word.start < at < word.end:
            return word.start if back else min(word.end, limit)
    return at


def _padded(
    start: float, end: float, words: tuple[SpokenWord, ...], limit: float
) -> tuple[float, float]:
    """A little room either side of speech, short of the neighbouring words."""
    if any(start <= w.start <= start + SPEECH_EDGE_SECONDS for w in words):
        before = max((w.end for w in words if w.end <= start), default=0.0)
        start = max(start - PAD_BEFORE_SECONDS, before, 0.0)
    if any(end - SPEECH_EDGE_SECONDS <= w.end <= end for w in words):
        after = min((w.start for w in words if w.start >= end), default=limit)
        end = min(end + PAD_AFTER_SECONDS, after, limit)
    return start, end


def _follows(prev: Cut, start: float, end: float) -> bool:
    """The stretch carries straight on from the one before it in the source."""
    gap = start - prev.end
    carries_on = _OVERLAP <= gap <= JOIN_GAP_SECONDS
    return bool(carries_on and prev.start < start and end > prev.end)


def _meets(asked_end: float, segment: PlanSegment) -> bool:
    """The plan itself put this stretch right after the one before it."""
    gap = segment.start - asked_end
    return -SPEECH_EDGE_SECONDS <= gap <= JOIN_GAP_SECONDS and segment.end > asked_end


def _same_shot(opened: PlanSegment, segment: PlanSegment) -> bool:
    """Carrying straight on, the stretch is part of the same cut - unless it
    is framed differently or comes in with a transition of its own, which
    only a cut of its own can show."""
    return segment.framing == opened.framing and (
        getattr(segment, "transition_in", "none") == "none"
    )


def _unjumped(cuts: list[Cut]) -> list[Cut]:
    """Every jump between two takes of one shot turned into a push-in."""
    out = cuts[:1]
    for cut in cuts[1:]:
        prev = out[-1]
        jump = 0 <= cut.start - prev.end <= JUMP_WINDOW_SECONDS
        if jump and cut.zoom == prev.zoom:
            cut = cut.model_copy(update={"zoom": 1.0 if prev.zoom > 1 else CLOSE_ZOOM})
        out.append(cut)
    return out


def _overlaps(cuts: list[Cut], start: float, end: float) -> bool:
    """A stretch already kept would play twice."""
    return any(start < cut.end and cut.start < end for cut in cuts)
