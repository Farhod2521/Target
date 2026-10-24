"""An :class:`~videokit.models.EditSpec` written out as Shotstack's edit JSON."""

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
MAX_EDIT_BYTES: Final = 380_000
FPS: Final = 30

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
    its transition and its sound ramps."""
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
