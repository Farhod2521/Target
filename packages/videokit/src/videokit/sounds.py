"""Short sounds under the graphics: a pop as a panel lands, a whoosh into
a new part, a ding on the closing card."""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Final

from videokit.media import _run, _run_both

FOLDER: Final = Path(__file__).parent / "sfx"
CATALOGUE: Final = FOLDER / "sounds.json"
SOUND_VOLUME: Final = 0.6
PEAK_DB: Final = -6.0
AUDIBLE_DB: Final = -30.0


@dataclass(frozen=True, slots=True)
class Sound:
    """One sound: its name, what it was made from, its file and length."""

    name: str
    prompt: str
    seconds: float
    length: float
    path: Path
    volume: float = SOUND_VOLUME

    @property
    def ready(self) -> bool:
        """The file is here and its length was measured."""
        return self.length > 0 and self.path.is_file()


@cache
def sounds() -> dict[str, Sound]:
    """Every sound described in the catalogue, by name."""
    raw = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    return {
        name: Sound(
            name=name,
            prompt=item["prompt"],
            seconds=float(item["seconds"]),
            length=float(item.get("length", 0)),
            path=FOLDER / f"{name}.mp3",
            volume=float(item.get("volume", SOUND_VOLUME)),
        )
        for name, item in raw.items()
    }


def sound_length(
    path: Path, *, ffprobe: str = "ffprobe", timeout: float = 30.0
) -> float:
    """How long a sound file plays, in seconds."""
    out = _run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        timeout=timeout,
    )  # fmt: skip
    return round(float(out.decode().strip() or 0), 3)


def peak_db(path: Path, *, ffmpeg: str = "ffmpeg", timeout: float = 30.0) -> float:
    """The loudest moment of a sound file, in dB under full scale."""
    _out, err = _run_both(
        [ffmpeg, "-hide_banner", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"],
        timeout=timeout,
    )  # fmt: skip
    found = re.search(r"max_volume: (-?[0-9.]+) dB", err)
    return float(found.group(1)) if found else -91.0


def level_sound(
    raw: Path, *, to: Path, ffmpeg: str = "ffmpeg", timeout: float = 60.0
) -> Path:
    """``raw`` brought to :data:`PEAK_DB` at its peak, the silence either
    side cut so it lands on its moment, as MP3."""
    gain = PEAK_DB - peak_db(raw, ffmpeg=ffmpeg, timeout=timeout)
    trim = "silenceremove=start_periods=1:start_threshold=-45dB"
    _run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
         "-af", f"volume={gain:.1f}dB,{trim},areverse,{trim},areverse",
         "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "128k",
         str(to)],
        timeout=timeout,
    )  # fmt: skip
    return to
