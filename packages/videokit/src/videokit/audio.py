"""The sound of a montage: no clicks at cuts, music under the voice, and
short sounds on the graphics.

**Cuts.** Two stretches of speech butted together click, and the room
tone jumps. Every cut's sound comes up over :data:`RAMP_SECONDS` and goes
down over the same at its end - too short to hear as a fade, long enough
to take the click away. A cut played as several clips (it crosses a
layout change) ramps only at its own ends.

**Ducking.** Music sits at its full level in the gaps and drops to
:data:`DUCKED` of it while anyone speaks, easing between the two. Pauses
shorter than :data:`DUCK_JOIN_SECONDS` do not let it back up - a level
pumping between words is worse than one that stays down.

**Sounds.** Each component plays the sound its manifest names as it
comes in and one on each beat its manifest gives a sound (a stamp's thud,
stars' sparkle); the opening headline rises in over a soft riser; a cut
that comes in with ``slide``, ``zoom``, ``flash`` or ``burst`` plays its
own. Sounds that would play together go on separate tracks.
"""

from collections.abc import Sequence
from itertools import pairwise
from typing import Any, Final

from videokit.components import component
from videokit.models import ComponentUse, EditSpec
from videokit.sounds import sounds

RAMP_SECONDS: Final = 0.06
DUCKED: Final = 0.3
DUCK_RAMP_SECONDS: Final = 0.3
DUCK_JOIN_SECONDS: Final = 0.6
# A headline that starts this early opens the video, and rises in.
OPENING: Final = 0.5
TRANSITION_SOUNDS: Final[dict[str, str]] = {
    "slide": "whoosh",
    "zoom": "swoosh",
    "flash": "snap",
    "burst": "whoosh",
}


def cut_volume(length: float, *, head: float, tail: float) -> list[dict[str, Any]]:
    """A clip's volume, by its clock: up over ``head`` seconds, down over ``tail``.

    Zero for an end that is not a cut - a layout change inside one cut.
    """
    head, tail = min(head, length / 3), min(tail, length / 3)
    points = [(0.0, 0.0 if head else 1.0), (head, 1.0), (length - tail, 1.0)]
    return _tweens([*points, (length, 0.0 if tail else 1.0)])


def duck(
    speech: Sequence[tuple[float, float]],
    *,
    length: float,
    level: float,
) -> list[dict[str, Any]]:
    """Music volume over ``length`` seconds: ``level`` in the gaps, lower
    under ``speech`` (``(start, end)`` pairs on the same clock)."""
    low = level * DUCKED
    points = [(0.0, level)]
    for start, end in _joined(speech):
        begin = max(start - DUCK_RAMP_SECONDS, points[-1][0])
        points += [
            (begin, level),
            (max(start, begin), low),
            (min(end, length), low),
            (min(end + DUCK_RAMP_SECONDS, length), level),
        ]
    return _tweens([*points, (length, level)])


def _tweens(points: list[tuple[float, float]]) -> list[dict[str, Any]]:
    """Straight lines between ``(time, value)`` points; equal times jump."""
    return [
        _volume(low, high, start, end - start)
        for (start, low), (end, high) in pairwise(points)
        if end - start > 1e-6
    ]


def _joined(speech: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for start, end in sorted(speech):
        if out and start - out[-1][1] < DUCK_JOIN_SECONDS:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _volume(low: float, high: float, start: float, length: float) -> dict[str, Any]:
    return {
        "from": round(low, 4),
        "to": round(high, 4),
        "start": round(start, 3),
        "length": round(length, 3),
        "interpolation": "linear",
    }


def sound_tracks(
    spec: EditSpec, *, cut_starts: Sequence[float]
) -> list[dict[str, Any]]:
    """Tracks of short sounds: each component's, and each transition's.

    ``cut_starts`` is where each cut begins in the finished video.
    """
    cues = [cue for use in spec.components for cue in _cues(use)]
    cues += [
        (at, TRANSITION_SOUNDS.get(cut.enter, ""))
        for at, cut in zip(cut_starts, spec.cuts, strict=True)
    ]
    known = sounds()
    lanes: list[list[dict[str, Any]]] = []
    for at, name in sorted(cues):
        url = spec.sound_urls.get(name)
        if not url or name not in known or not known[name].ready:
            continue
        clip = {
            "asset": {"type": "audio", "src": url, "volume": known[name].volume},
            "start": round(at, 3),
            "length": known[name].length,
        }
        free = next((lane for lane in lanes if _ends(lane[-1]) <= at + 1e-6), None)
        if free is None:
            lanes.append([clip])
        else:
            free.append(clip)
    return [{"clips": lane} for lane in lanes]


def _cues(use: ComponentUse) -> list[tuple[float, str]]:
    """A component's sounds: as it comes in, on each beat that has one, and
    a riser under the headline that opens the video."""
    item = component(use.name)
    cues = [(use.start, item.sfx)]
    beats = item.beats_at(use.start, use.beats)
    for beat, sound in item.sounds:
        moments = [use.start] if beat == "start" else beats.get(beat, [])
        for at in moments if isinstance(moments, list) else [moments]:
            cues.append((round(min(at, use.start + use.length), 3), sound))
    if item.hook and use.start < OPENING:
        cues.append((use.start, "riser"))
    return cues


def _ends(clip: dict[str, Any]) -> float:
    return float(clip["start"]) + float(clip["length"])
