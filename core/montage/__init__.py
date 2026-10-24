"""Turning one uploaded video into a shorter one worth watching.

No Django and no network. What is said, what is shown and what the owner
asked for come in as values; the stretches to keep, the text over them and
the subtitles go out as values. Claude proposes (:mod:`core.montage.plan`),
this package checks and fixes the proposal (:mod:`core.montage.settle`),
and :mod:`videokit` renders it.
"""

from core.montage.brief import frame_every, transcript_lines
from core.montage.captions import Line, SpokenWord, lines_for, srt
from core.montage.errors import MontageError, NothingToKeepError
from core.montage.plan import MontagePlan, PlanSegment, PlanText
from core.montage.settle import Settled, settle

__all__ = [
    "Line",
    "MontageError",
    "MontagePlan",
    "NothingToKeepError",
    "PlanSegment",
    "PlanText",
    "Settled",
    "SpokenWord",
    "frame_every",
    "lines_for",
    "settle",
    "srt",
    "transcript_lines",
]
