"""videokit.sync: the beep, the flash and a colour found again in a clip."""

import shutil
import subprocess
from pathlib import Path

import pytest
from videokit.sync import (
    FPS,
    beep_onsets,
    colour_onsets,
    flash_onsets,
    paired_offset,
    sync_clip,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="no ffmpeg")
FRAME = 1 / FPS


def test_the_clip_beeps_and_flashes_on_every_second(tmp_path: Path) -> None:
    clip = sync_clip(tmp_path / "sync.mp4", seconds=5)

    beeps = beep_onsets(clip)
    flashes = flash_onsets(clip)

    assert [round(b) for b in beeps] == [1, 2, 3, 4]
    assert [round(f) for f in flashes] == [1, 2, 3, 4]
    offset = paired_offset(flashes, beeps)
    assert offset is not None and abs(offset) < FRAME


def test_sound_moved_late_is_measured_late(tmp_path: Path) -> None:
    clip = sync_clip(tmp_path / "sync.mp4", seconds=5)
    late = tmp_path / "late.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(clip),
         "-af", "adelay=100", "-c:v", "copy", str(late)],
        check=True,
    )  # fmt: skip

    offset = paired_offset(flash_onsets(late), beep_onsets(late))

    assert offset is not None
    assert abs(offset - 0.1) < 0.01


def test_a_colour_showing_in_a_box_is_found(tmp_path: Path) -> None:
    clip = tmp_path / "green.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s=540x960:r={FPS}:d=4",
         "-vf", "drawbox=x=100:y=700:w=200:h=60:color=0x00ff00:t=fill:"
                "enable='gte(t,2)'",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )  # fmt: skip

    found = colour_onsets(clip, box=(0.0, 0.6, 1.0, 0.85), colour=(0, 255, 0))

    assert len(found) == 1 and abs(found[0] - 2.0) <= FRAME
