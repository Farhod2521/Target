"""Reading a video on this machine: how long, what it shows, what it says."""

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Final

from videokit.errors import MediaToolError
from videokit.models import AudioTreatment, Frame, MediaInfo

DEFAULT_TIMEOUT_SECONDS: Final = 300.0
_JPEG_QUALITY: Final = "5"

PREPARE_TIMEOUT_SECONDS: Final = 480.0
PREPARED_LONG_SIDE: Final = 1920
PREPARED_FPS: Final = 30

_LEVEL: Final = "loudnorm=I=-14:TP=-1.5:LRA=11"
_VOICE: Final = "highpass=f=80,lowpass=f=12000,afftdn=nr=12:nf=-30:tn=1"
_AUDIO_FILTERS: Final[dict[AudioTreatment, str]] = {
    "none": "",
    "level": _LEVEL,
    "voice": f"{_VOICE},{_LEVEL}",
}


def probe(
    path: Path, *, ffprobe: str = "ffprobe", timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> MediaInfo:
    """Length, picture size and whether there is any sound."""
    out = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=timeout,
    )
    try:
        data: dict[str, Any] = json.loads(out or b"{}")
    except ValueError as exc:
        raise MediaToolError("ffprobe answered something that is not JSON") from exc

    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaToolError("the file has no picture")
    duration = _seconds(data.get("format", {}).get("duration")) or _seconds(
        video.get("duration")
    )
    return MediaInfo(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


SCENE_THRESHOLD: Final = 0.3
_PTS_TIME: Final = re.compile(r"pts_time:([0-9.]+)")


def frames(
    path: Path,
    *,
    every: float,
    width: int,
    limit: int,
    ffmpeg: str = "ffmpeg",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[Frame]:
    """One still every ``every`` seconds, at most ``limit`` of them."""
    if every <= 0 or limit <= 0:
        return []
    with tempfile.TemporaryDirectory(prefix="videokit-") as folder:
        pattern = Path(folder) / "frame_%05d.jpg"
        _run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vf",
                f"fps=1/{every},scale={width}:-2",
                "-frames:v",
                str(limit),
                "-q:v",
                _JPEG_QUALITY,
                str(pattern),
            ],
            timeout=timeout,
        )
        stills = sorted(Path(folder).glob("frame_*.jpg"))
        return [
            Frame(at=round(index * every, 3), jpeg=still.read_bytes())
            for index, still in enumerate(stills)
        ]


def scene_changes(
    path: Path,
    *,
    threshold: float = SCENE_THRESHOLD,
    ffmpeg: str = "ffmpeg",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[float]:
    """The moments the picture changes (FFmpeg's scene score over
    ``threshold``), in seconds, in order. Read on a small copy of each frame:
    a change of shot shows at any size, and the full one is slow."""
    _out, said = _run_both(
        [ffmpeg, "-hide_banner", "-i", str(path), "-an",
         "-vf", f"scale=160:-2,select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"],
        timeout=timeout,
    )  # fmt: skip
    return [round(float(found), 3) for found in _PTS_TIME.findall(said)]


def frames_at(
    path: Path,
    *,
    moments: list[float],
    width: int,
    ffmpeg: str = "ffmpeg",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[Frame]:
    """One still at each of ``moments`` (seconds), in order: each its own
    seek, straight to the moment. A moment past the end gives no still."""
    found = []
    with tempfile.TemporaryDirectory(prefix="videokit-") as folder:
        for index, at in enumerate(moments):
            still = Path(folder) / f"at_{index:03d}.jpg"
            _run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{max(at, 0.0):.3f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={width}:-2",
                    "-q:v",
                    _JPEG_QUALITY,
                    str(still),
                ],
                timeout=timeout,
            )
            if still.exists():
                found.append(Frame(at=round(at, 3), jpeg=still.read_bytes()))
    return found


def prepare(
    path: Path,
    *,
    to: Path,
    audio: AudioTreatment,
    ffmpeg: str = "ffmpeg",
    timeout: float = PREPARE_TIMEOUT_SECONDS,
) -> Path:
    """One clean MP4 of the upload: H.264, steady frames, sound treated."""
    side = PREPARED_LONG_SIDE
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-vf",
        (
            f"scale=w='min({side},iw)':h='min({side},ih)'"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"fps={PREPARED_FPS},format=yuv420p"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
    ]
    if audio == "none":
        command += ["-an"]
    else:
        command += [
            "-map",
            "0:a:0",
            "-af",
            _AUDIO_FILTERS[audio],
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
        ]
    command += ["-movflags", "+faststart", str(to)]
    _run(command, timeout=timeout)
    return to


def extract_audio(
    path: Path,
    *,
    to: Path,
    ffmpeg: str = "ffmpeg",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Path:
    """The sound alone, mono and small, for a transcript."""
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(to),
        ],
        timeout=timeout,
    )
    return to


def _run(command: list[str], *, timeout: float) -> bytes:
    return _run_both(command, timeout=timeout)[0]


def _run_both(command: list[str], *, timeout: float) -> tuple[bytes, str]:
    """What a tool wrote out and what it said on the side (its report)."""
    try:
        done = subprocess.run(
            command, capture_output=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        raise MediaToolError(f"{command[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaToolError(f"{command[0]} took longer than {timeout:.0f}s") from exc
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise MediaToolError(f"{command[0]} failed: {detail[-1] if detail else '?'}")
    return done.stdout, done.stderr.decode("utf-8", "replace")


def _seconds(value: Any) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0
