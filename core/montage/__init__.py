"""Turning one uploaded video into a shorter one worth watching."""

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
