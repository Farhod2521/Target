"""What Claude is shown, written as text it can point back into.

Every number in here is a second in the source, so every number Claude
writes back can be checked against the file.
"""

from typing import Any

from videokit.components import Component
from videokit.components.registry import PropSpec
from videokit.icons import ICONS

from core.montage.captions import SpokenWord

NOTHING_SAID = "(nothing is said in this video)"

# The transcript is shown phrase by phrase rather than word by word: a
# phrase per line reads like speech and still carries a time Claude can
# cut at. A gap this long between words starts a new phrase.
PHRASE_GAP_SECONDS = 0.5
MAX_PHRASE_WORDS = 12

# Stills cost tokens, so a long file gets them further apart. Never closer
# than every two seconds, never more than this many in all.
MIN_FRAME_EVERY = 2.0
MAX_FRAMES = 40


# The stills the planner is shown: one where the picture changes, at
# least this many and at most that many, and one every few seconds where
# it never does. Each still is tokens, and a talking head looks the same
# from one second to the next.
MIN_SHOWN = 6
MAX_SHOWN = 16
QUIET_EVERY = 5.0
# A still a moment after the change, not on the blur of the cut itself.
AFTER_CHANGE = 0.4
_APART = 1.5


def shown_moments(changes: list[float], *, duration: float) -> list[float]:
    """When to take the stills the planner is shown, in order."""
    if duration <= 0:
        return []
    found = _apart([min(0.5, duration / 2)] + [c + AFTER_CHANGE for c in changes])
    if len(found) < MIN_SHOWN:
        grid = [
            QUIET_EVERY / 2 + i * QUIET_EVERY for i in range(int(duration // 5) + 1)
        ]
        found = _apart(sorted(found + grid))
    if len(found) < MIN_SHOWN:
        step = duration / MIN_SHOWN
        found = [round(step / 2 + i * step, 3) for i in range(MIN_SHOWN)]
    found = [at for at in found if at < duration]
    if len(found) > MAX_SHOWN:
        found = [
            found[round(i * (len(found) - 1) / (MAX_SHOWN - 1))]
            for i in range(MAX_SHOWN)
        ]
    return [round(at, 3) for at in found]


def _apart(moments: list[float]) -> list[float]:
    kept: list[float] = []
    for at in sorted(moments):
        if not kept or at - kept[-1] >= _APART:
            kept.append(at)
    return kept


def frame_every(source_seconds: float) -> float:
    """How far apart the stills are taken, for a file this long."""
    return round(max(MIN_FRAME_EVERY, source_seconds / MAX_FRAMES), 2)


def transcript_lines(words: tuple[SpokenWord, ...]) -> str:
    """``[12.40-15.10] the words said then``, one phrase per line."""
    if not words:
        return NOTHING_SAID
    return "\n".join(
        f"[{words[a].start:.2f}-{words[b].end:.2f}] {_text(words, a, b)}"
        for a, b in _phrases(words)
    )


def indexed_transcript_lines(words: tuple[SpokenWord, ...]) -> str:
    """``[12.40-15.10] (#41-#47) the words``: times to cut at, numbers to
    anchor a component to."""
    if not words:
        return NOTHING_SAID
    return "\n".join(
        f"[{words[a].start:.2f}-{words[b].end:.2f}] (#{a}-#{b}) {_text(words, a, b)}"
        for a, b in _phrases(words)
    )


def faces_for_prompt(faces: list[list[Any]], *, stills: int) -> str:
    """Where the speaker's face was on the stills, in words.

    ``faces`` as the montage keeps them: ``[second, width, height, box,
    guard, score]`` with the box and the guard as shares of the still.
    """
    if not faces:
        return f"No face was found on the {stills} stills."
    middles = [((f[4][0] + f[4][2]) / 2, (f[4][1] + f[4][3]) / 2) for f in faces]
    x = sum(m[0] for m in middles) / len(middles)
    y = sum(m[1] for m in middles) / len(middles)
    tall = sum(f[3][3] - f[3][1] for f in faces) / len(faces)
    return (
        f"Found on {len(faces)} of {stills} stills. Its eyes and mouth are "
        f"usually {round(x * 100)}% across and {round(y * 100)}% down the "
        f"frame; the face is about {round(tall * 100)}% of the frame's height. "
        "The code keeps every graphic off the eyes and the mouth."
    )


def catalogue(items: list[Component]) -> str:
    """The components a planner may place, written from their manifests."""
    return "\n\n".join(_entry(item) for item in items)


def _entry(item: Component) -> str:
    needs = f"; needs layout {item.layout}" if item.layout else ""
    head = (
        f"- **{item.name}** - zones {', '.join(item.zones)}; "
        f"{item.min_seconds:g}-{item.max_seconds:g} s{needs}. {item.description}"
    )
    props = [
        f"  - `{p.name}`{'' if p.required else ' (optional)'}: "
        + _kind(p)
        + (f". {p.description}" if p.description else "")
        for p in item.props
    ]
    beats = [
        f"  - beat `{name}`"
        + (" (one word per item)" if item.beat_is_list(name) else "")
        + f": {what}"
        for name, what in item.beats
    ]
    body = props or ["  - no props"]
    return "\n".join([head, *body, *beats])


def _kind(prop: PropSpec) -> str:
    if prop.kind == "icon":
        return "an icon, one of " + ", ".join(ICONS)
    if prop.kind == "text":
        return f"text, at most {prop.max_length} characters"
    return (
        f"{prop.min_items}-{prop.max_items} texts, each at most "
        f"{prop.max_length} characters"
    )


def _phrases(words: tuple[SpokenWord, ...]) -> list[tuple[int, int]]:
    """First and last index of each phrase."""
    spans: list[tuple[int, int]] = []
    first = 0
    for index in range(1, len(words)):
        gap = words[index].start - words[index - 1].end
        if gap > PHRASE_GAP_SECONDS or index - first >= MAX_PHRASE_WORDS:
            spans.append((first, index - 1))
            first = index
    spans.append((first, len(words) - 1))
    return spans


def _text(words: tuple[SpokenWord, ...], first: int, last: int) -> str:
    return " ".join(word.text for word in words[first : last + 1])
