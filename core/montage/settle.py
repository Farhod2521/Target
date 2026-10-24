"""Claude's plan, made safe to render.

The plan is read as a proposal, never as a command. Every stretch is held
inside the file it names, a boundary that falls mid-word is moved to the
edge of that word, stretches too short to see are dropped, and the whole
is held near the length the owner asked for. What survives is what is
rendered - and if nothing does, the montage stops here rather than paying
for an empty video.

Three things an editor does by hand are done here, where they can be
tested rather than hoped for from the model:

- **Breath room.** A cut exactly on a word's edges clips its first
  consonant and its last; each stretch opens a little before its first
  word and closes a little after its last, without reaching into the
  words either side.
- **No needless cuts.** Two stretches that follow each other in the
  source with next to nothing between them are one stretch - unless the
  plan framed them differently or brought the second in with a
  transition; then they stay two cuts that meet exactly.
- **No dead air** (v3). A long silence inside a kept stretch is cut out;
  see :mod:`core.montage.pauses`.
- **No greeting first** (v3). A video that opens on "Assalomu alaykum"
  starts on the word after it; see :mod:`core.montage.greetings`.
- **No visible jumps.** Two takes of the same shot played back to back
  jump on screen. When a stretch follows the one before it closely in the
  source and both have the same framing, the second is pushed in (or back
  out), which reads as a deliberate cut.
"""

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

# Shorter than this is a flicker, not a shot.
MIN_SEGMENT_SECONDS = 0.6
# Room left before the first word and after the last of a stretch.
PAD_BEFORE_SECONDS = 0.08
PAD_AFTER_SECONDS = 0.18
# A word this close to a boundary means the boundary is on speech.
SPEECH_EDGE_SECONDS = 0.05
_OVERLAP = -(PAD_BEFORE_SECONDS + PAD_AFTER_SECONDS) - 0.01
# A gap this small between two stretches in source order is no cut at all.
JOIN_GAP_SECONDS = 0.15
# A later stretch that starts within this of the previous one's end is most
# likely the same shot - the kind of cut that jumps.
JUMP_WINDOW_SECONDS = 20.0
# How far a "close" stretch pushes in.
CLOSE_ZOOM = 1.15
# More new parts than this and nothing reads as a new part.
MOST_CHANGES = 4
# How far past the asked length the finished video may run before the
# last stretches are dropped. A little slack, because cutting a sentence
# in half to save two seconds is worse than two seconds.
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
    """The plan, held to the file, to whole words and to the asked length.

    ``NothingToKeepError`` when no stretch survives.
    """
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
    moments to punch in on.

    Each cut carries how it comes in (``Cut.enter``); the first always
    opens plainly.
    """

    cuts: tuple[Cut, ...]
    # The whole video: the words, then ``tail`` seconds of closing card.
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
    """A v3 plan (see :func:`core.montage.plan.plan_schema`) made safe to render.

    ``plan`` is typed loosely because its class is built per montage. The
    words are held to :func:`speech_limits`: the closing card comes after
    them, inside the length asked for.
    ``NothingToKeepError`` when no stretch survives.
    """
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
    no longer than the words may run (:func:`speech_limits`).

    ``NothingToKeepError`` when none does.
    """
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
    """A little room either side of speech, short of the neighbouring words.

    Only where the stretch opens or closes on a word. A boundary in a
    silence was placed there on purpose and is left where it is.
    """
    if any(start <= w.start <= start + SPEECH_EDGE_SECONDS for w in words):
        before = max((w.end for w in words if w.end <= start), default=0.0)
        start = max(start - PAD_BEFORE_SECONDS, before, 0.0)
    if any(end - SPEECH_EDGE_SECONDS <= w.end <= end for w in words):
        after = min((w.start for w in words if w.start >= end), default=limit)
        end = min(end + PAD_AFTER_SECONDS, after, limit)
    return start, end


def _follows(prev: Cut, start: float, end: float) -> bool:
    """The stretch carries straight on from the one before it in the source."""
    # Below nought only by the breath room the two were given, never by a
    # stretch played twice.
    gap = start - prev.end
    carries_on = _OVERLAP <= gap <= JOIN_GAP_SECONDS
    return bool(carries_on and prev.start < start and end > prev.end)


def _meets(asked_end: float, segment: PlanSegment) -> bool:
    """The plan itself put this stretch right after the one before it.

    Two stretches that meet in the middle of a word both snap to that
    word's edges and overlap by it - which is not a stretch played twice.
    Judged on the times the plan asked for, before any snapping.
    """
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
