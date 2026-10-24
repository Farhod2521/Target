"""The headline the video opens on.

A feed decides in the first half second, so the opening headline is on
screen from the very first frame: the planner's, or - when it planned
none - the first sentence said. It stays until its sentence ends, up to
:data:`HOOK_MAX_SECONDS`, longer than its manifest lets the same graphic
stay anywhere else in the video.
"""

from dataclasses import replace
from typing import Final

from videokit.components import component

from core.montage.captions import SpokenWord
from core.montage.fitting import Want

HOOK_MAX_WORDS: Final = 7
# How long the opening headline may stay: until its sentence ends, but
# never longer than this, whatever its manifest says.
HOOK_MAX_SECONDS: Final = 5.0
# A headline asked for this early opens the video; a later one is a
# headline in the middle of it.
OPENING_SECONDS: Final = 4.0
_SENTENCE_END: Final = (".", "!", "?", "…")
# Punctuation a headline does not end on: commas, colons, dashes.
_TRAILING: Final = ",;:- " + chr(0x2013) + chr(0x2014)


def first_hook(asked: list[Want]) -> Want | None:
    """The planner's opening headline: the earliest headline it asked for,
    unless that one is a mid-video headline (anything but ``hook_title``)
    asked for well after the opening."""
    hooks = sorted((w for w in asked if component(w.name).hook), key=lambda w: w.start)
    if not hooks:
        return None
    first = hooks[0]
    if first.name != "hook_title" and first.start > OPENING_SECONDS:
        return None
    return first


def auto_hook(
    words: tuple[SpokenWord, ...], times: dict[int, tuple[float, float]]
) -> list[Want]:
    """The first sentence said in the finished video, as a headline."""
    order = sorted(times, key=lambda index: times[index][0])
    chosen: list[int] = []
    for index in order[:HOOK_MAX_WORDS]:
        chosen.append(index)
        if words[index].text.endswith(_SENTENCE_END):
            break
    item = component("hook_title")
    limit = next(p.max_length for p in item.props if p.name == "text")
    while chosen and len(_joined(words, chosen)) > limit:
        chosen.pop()
    text = _joined(words, chosen)
    if len(text) < 3:
        return []
    start = times[chosen[0]][0]
    said = times[chosen[-1]][1] - start
    seconds = min(max(said, item.min_seconds), HOOK_MAX_SECONDS)
    return [Want("hook_title", "TOP_TITLE", start, seconds, {"text": text}, said=said)]


def opening_hook(hook: Want) -> Want:
    """The headline from the very first frame: a feed decides in the first
    half second. It stays until its words end - past its manifest's own
    limit, up to :data:`HOOK_MAX_SECONDS`."""
    item = component(hook.name)
    asked_end = hook.start + max(hook.said, hook.length)
    length = min(max(asked_end, item.min_seconds), HOOK_MAX_SECONDS)
    return replace(hook, start=0.0, length=length)


def _joined(words: tuple[SpokenWord, ...], chosen: list[int]) -> str:
    return " ".join(words[index].text for index in chosen).rstrip(_TRAILING)
