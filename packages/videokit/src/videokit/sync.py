"""Measuring whether sound, picture and subtitles land on the same moment."""

import math
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from videokit.media import DEFAULT_TIMEOUT_SECONDS, _run

SAMPLE_RATE: Final = 16_000
FPS: Final = 30
BEEP_SECONDS: Final = 0.05
QUIET_BEFORE: Final = 0.2
_WINDOW: Final = 0.002


def sync_clip(
    to: Path, *, seconds: int = 10, ffmpeg: str = "ffmpeg", size: str = "540x960"
) -> Path:
    """A black clip that beeps and flashes white at 1 s, 2 s, ... ``seconds-1``."""
    flash = f"lt(mod(t\\,1)\\,{1 / FPS:.4f})*gte(t\\,0.5)"
    tone = f"if(lt(mod(t,1),{BEEP_SECONDS})*gte(t,0.5),0.8*sin(2*PI*1000*t),0)"
    _run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={size}:r={FPS}:d={seconds}",
            "-f", "lavfi", "-i", f"aevalsrc='{tone}':s=48000:d={seconds}",
            "-vf", f"drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='{flash}'",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-shortest", str(to),
        ],
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )  # fmt: skip
    return to


def beep_onsets(path: Path, *, ffmpeg: str = "ffmpeg") -> list[float]:
    """Seconds at which a sound starts after :data:`QUIET_BEFORE` of quiet."""
    levels = _levels(path, ffmpeg=ffmpeg, window=_WINDOW)
    loud = max(levels, default=0.0)
    return _onsets(levels, step=_WINDOW, threshold=loud * 0.25)


def speech_onsets(
    path: Path, *, ffmpeg: str = "ffmpeg", quiet: float = 0.3
) -> list[float]:
    """Where speech starts again after at least ``quiet`` seconds of near-silence."""
    window = 0.01
    levels = _levels(path, ffmpeg=ffmpeg, window=window)
    if not levels:
        return []
    ordered = sorted(levels)
    threshold = ordered[int(len(ordered) * 0.95)] * 0.12
    return _onsets(levels, step=window, threshold=threshold, quiet=quiet)


def flash_onsets(path: Path, *, ffmpeg: str = "ffmpeg") -> list[float]:
    """Seconds at which the whole frame turns white."""
    frames = _frames(path, ffmpeg=ffmpeg, crop="", size=8, gray=True)
    lit = [sum(frame) / len(frame) > 200 for frame in frames]
    return [i / FPS for i, on in enumerate(lit) if on and (i == 0 or not lit[i - 1])]


def colour_onsets(
    path: Path,
    *,
    box: tuple[float, float, float, float],
    colour: tuple[int, int, int],
    share: float = 0.002,
    ffmpeg: str = "ffmpeg",
) -> list[float]:
    """Seconds at which ``colour`` starts to cover ``share`` of ``box``."""
    left, top, right, bottom = box
    crop = (
        f"crop=iw*{right - left:.4f}:ih*{bottom - top:.4f}:iw*{left:.4f}:ih*{top:.4f},"
    )
    frames = _frames(path, ffmpeg=ffmpeg, crop=crop, size=96, gray=False)
    shown = []
    for frame in frames:
        pixels = len(frame) // 3
        near = sum(
            1
            for i in range(0, len(frame), 3)
            if abs(frame[i] - colour[0])
            + abs(frame[i + 1] - colour[1])
            + abs(frame[i + 2] - colour[2])
            < 90
        )
        shown.append(near >= pixels * share)
    return [
        i / FPS for i, on in enumerate(shown) if on and (i == 0 or not shown[i - 1])
    ]


def paired_offset(earlier: Sequence[float], later: Sequence[float]) -> float | None:
    """The median of ``later - earlier`` over moments that pair up within
    half a second; None when none do."""
    gaps = []
    for moment in earlier:
        near = min(later, key=lambda at: abs(at - moment), default=None)
        if near is not None and abs(near - moment) < 0.5:
            gaps.append(near - moment)
    return statistics.median(gaps) if gaps else None


def _levels(path: Path, *, ffmpeg: str, window: float) -> list[float]:
    raw = _run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
        ],
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )  # fmt: skip
    samples = memoryview(raw).cast("h")
    size = max(1, round(SAMPLE_RATE * window))
    return [
        math.sqrt(sum(s * s for s in samples[i : i + size]) / size)
        for i in range(0, len(samples) - size + 1, size)
    ]


def _onsets(
    levels: Sequence[float],
    *,
    step: float,
    threshold: float,
    quiet: float = QUIET_BEFORE,
) -> list[float]:
    found: list[float] = []
    silent = 0.0
    for index, level in enumerate(levels):
        if level < threshold:
            silent += step
            continue
        if silent >= quiet:
            found.append(round(index * step, 4))
        silent = 0.0
    return found


def _frames(
    path: Path, *, ffmpeg: str, crop: str, size: int, gray: bool
) -> list[bytes]:
    pixel = "gray" if gray else "rgb24"
    raw = _run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-vf", f"fps={FPS},{crop}scale={size}:{size},format={pixel}",
            "-f", "rawvideo", "-",
        ],
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )  # fmt: skip
    frame = size * size * (1 if gray else 3)
    return [raw[i : i + frame] for i in range(0, len(raw) - frame + 1, frame)]
