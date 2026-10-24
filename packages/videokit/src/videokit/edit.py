"""An :class:`~videokit.models.EditSpec` written out as Shotstack's edit JSON.

Kept apart from the client so the shape can be tested without a network
and read without one: this file is the whole answer to "what does a
montage look like to Shotstack".

**Tracks are drawn top first.** A transition's flash over everything,
components over the picture (see :mod:`videokit.graphics`), then text,
then subtitles, then the footage, then short sounds and the music
underneath - a track higher in the list covers the ones below it.

**The cuts play back to back.** Each kept stretch becomes one clip that
starts where the previous one ended, trimmed into the source by its own
start. Order is the caller's: a plan may open on the strongest moment even
when it was said last. Between cuts there is no transition - a hard cut is
what short video is made of. The video opens on its first frame, picture
and headline at once - a feed decides in the first half second, and a
fade up from black spends it on nothing - and fades down at the very end,
so it does not stop dead.

**The closing card has time of its own** (``EditSpec.tail``): after the
last cut the source carries on, silent and as framed, under the card -
the words are never covered by it, and the card never shows a black
frame as it comes in.

**A push-in hides a jump.** A cut with ``zoom`` above one is scaled up for
its stretch. Two takes of one talking shot played back to back jump; the
same two with the second a little closer read as a deliberate edit.

**Moving** (``EditSpec.motion``): each cut also creeps closer as it plays,
punches in where the plan marked the point, comes in with its transition,
ramps its sound at both ends and plays the components' sounds - see
:mod:`videokit.motion` and :mod:`videokit.audio`. ``still`` is the edit
as it was before any of that, for montages planned the old way.

**The footage is cropped, never stretched.** ``fit: crop`` fills the
frame and keeps the picture's proportions; ``cover`` would stretch a
landscape clip to fill a portrait frame.

**Subtitles are word by word** when the spec carries their words, in the
brand's font and colours: one HTML5 clip per run of lines that sit in the
same band. Without words, an SRT file goes to Shotstack's caption asset,
which knows only when a line starts - see :mod:`videokit.captions`.

Sizes are written for a 1080-pixel short side and scaled to the frame
(:mod:`videokit.layout`). Text over the picture and the SRT fallback are
Roboto, Shotstack's fallback, which renders the same whether or not a font file loads -
though it has no Uzbek okina, which callers write as an apostrophe.
"""

import json
from typing import Any, Final

from videokit.audio import RAMP_SECONDS, cut_volume, duck, sound_tracks
from videokit.captions import srt_clip, text_width, word_clips
from videokit.graphics import component_tracks, pieces, placed, shift_at
from videokit.layout import scaled
from videokit.models import Cut, EditSpec, Overlay
from videokit.motion import (
    FLASH_BEFORE,
    FLASHES,
    SHOTSTACK_IN,
    Key,
    cut_keys,
    cut_starts,
    face_anchor,
    flash_clip,
    held_offset,
    scale_tweens,
    split_at,
    steps,
)

FONT: Final = "Roboto"
# Shotstack refuses an edit larger than 390 KB; this leaves room for
# what its own client adds around the body.
MAX_EDIT_BYTES: Final = 380_000
# The frame rate the footage is prepared at. Shotstack's default is 25,
# which drops every sixth frame of a phone clip.
FPS: Final = 30

# A line of text over the picture (the old way of planning).
_OVERLAY_FONT_PX: Final = 84
_TEXT_HEIGHT_PX: Final = 480


def build_edit(spec: EditSpec) -> dict[str, Any]:
    """The JSON body for one render request."""
    starts = cut_starts(spec.cuts)
    tracks: list[dict[str, Any]] = []
    if spec.motion == "moving":
        flashes = [
            flash_clip(at)
            for at, cut in zip(starts, spec.cuts, strict=True)
            if cut.enter in FLASHES and at > FLASH_BEFORE
        ]
        if flashes:
            tracks.append({"clips": flashes})
    tracks += component_tracks(spec)
    if spec.overlays:
        tracks.append({"clips": [_overlay(item, spec) for item in spec.overlays]})
    if spec.captions:
        tracks.append({"clips": word_clips(spec)})
    elif spec.captions_url:
        tracks.append({"clips": [srt_clip(spec, font=FONT)]})
    tracks.append({"clips": _footage(spec)})
    if spec.motion == "moving":
        tracks += sound_tracks(spec, cut_starts=starts)
    if spec.music_url:
        tracks.append({"clips": [_music(spec)]})

    return {
        "timeline": {"background": "#000000", "tracks": tracks},
        "output": {
            "format": "mp4",
            "resolution": spec.resolution,
            "aspectRatio": spec.aspect_ratio,
            "fps": FPS,
        },
    }


def edit_bytes(edit: dict[str, Any]) -> int:
    """How large an edit is on the wire, to compare with :data:`MAX_EDIT_BYTES`."""
    return len(json.dumps(edit).encode())


def output_length(cuts: tuple[Cut, ...]) -> float:
    """How long the kept stretches run end to end; the whole video is
    :attr:`EditSpec.length`, which adds the closing card's tail."""
    return round(sum(cut.end - cut.start for cut in cuts), 3)


def _footage(spec: EditSpec) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    cursor = 0.0
    for cut in spec.cuts:
        length = cut.end - cut.start
        keys = cut_keys(cut, at=cursor, punches=spec.punches)
        anchor = face_anchor(spec.faces, cursor, cursor + length)
        parts = pieces(cursor, cursor + length, spec.layouts)
        if spec.motion == "moving":
            parts = split_at(parts, [cursor + at for at in steps(keys)])
        for low, high, layout in parts:
            clip: dict[str, Any] = {
                "asset": {
                    "type": "video",
                    "src": spec.source_url,
                    "trim": round(cut.start + low - cursor, 3),
                },
                "start": round(low, 3),
                "length": round(high - low, 3),
                "fit": "crop",
            }
            if spec.motion == "moving":
                clip = _moving(
                    clip,
                    cut,
                    keys=keys,
                    low=low - cursor,
                    cut_length=length,
                    anchor=anchor,
                )
            elif cut.zoom > 1:
                clip["scale"] = round(cut.zoom, 3)
            shift = shift_at(spec.layouts, (low + high) / 2)
            clips.append(placed(clip, layout, shift))
        cursor += length
    if spec.tail > 0:
        clips.append(_tail(spec, at=cursor))
    # The first frame is the picture itself; only the end fades down.
    first = {key: value for key, value in clips[0].items() if key != "transition"}
    clips[0] = first
    last = clips[-1]
    clips[-1] = {**last, "transition": {**last.get("transition", {}), "out": "fade"}}
    return clips


def _tail(spec: EditSpec, *, at: float) -> dict[str, Any]:
    """The footage under the closing card: the source carrying on from
    ``tail_from``, silent, at the last cut's framing."""
    clip: dict[str, Any] = {
        "asset": {
            "type": "video",
            "src": spec.source_url,
            "trim": round(spec.tail_from, 3),
            "volume": 0,
        },
        "start": round(at, 3),
        "length": round(spec.tail, 3),
        "fit": "crop",
    }
    zoom = spec.cuts[-1].zoom
    if zoom > 1:
        clip["scale"] = round(zoom, 3)
    return clip


def _moving(
    clip: dict[str, Any],
    cut: Cut,
    *,
    keys: list[Key],
    low: float,
    cut_length: float,
    anchor: tuple[float, float] | None,
) -> dict[str, Any]:
    """A footage clip with its motion, held on the face at ``anchor``,
    its transition and its sound ramps.

    ``low`` is where the clip starts within its cut.
    """
    length = clip["length"]
    clip["scale"] = scale_tweens(keys, low, low + length)
    if anchor is not None:
        clip["offset"] = held_offset(clip["scale"], anchor)
    clip["asset"]["volume"] = cut_volume(
        length,
        head=RAMP_SECONDS if low < 1e-6 else 0.0,
        tail=RAMP_SECONDS if low + length >= cut_length - 1e-3 else 0.0,
    )
    if low < 1e-6 and cut.enter in SHOTSTACK_IN:
        clip["transition"] = {"in": SHOTSTACK_IN[cut.enter]}
    return clip


def _overlay(item: Overlay, spec: EditSpec) -> dict[str, Any]:
    return {
        "asset": {
            "type": "rich-text",
            "text": item.text,
            "font": {
                "family": FONT,
                "size": scaled(_OVERLAY_FONT_PX, spec.resolution),
                "color": "#ffffff",
                "weight": 800,
            },
            "background": {
                "color": "#000000",
                "opacity": 0.55,
                "borderRadius": scaled(27, spec.resolution),
            },
            "padding": scaled(36, spec.resolution),
            "animation": {"preset": "fadeIn", "duration": 0.4},
        },
        "start": round(item.start, 3),
        "length": round(item.length, 3),
        "width": text_width(spec),
        "height": scaled(_TEXT_HEIGHT_PX, spec.resolution),
        "position": item.position,
    }


def _music(spec: EditSpec) -> dict[str, Any]:
    """Music under the whole video; moving, it ducks under the speech."""
    volume: Any = spec.music_volume
    if spec.motion == "moving" and spec.captions:
        volume = duck(
            [(line.start, line.end) for line in spec.captions],
            length=spec.length,
            level=spec.music_volume,
        )
    return {
        "asset": {
            "type": "audio",
            "src": spec.music_url,
            "volume": volume,
            "effect": "fadeInFadeOut",
        },
        "start": 0,
        "length": "end",
    }
