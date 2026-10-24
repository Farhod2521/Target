"""Video montage, done somewhere else and prepared here.

Two halves. :mod:`videokit.media` reads a file on this machine with FFmpeg
- its length, a still every few seconds, its sound. :class:`Shotstack`
takes the file, an :class:`EditSpec` built into JSON by :func:`build_edit`,
and returns the finished video.

The package knows nothing about advertising, accounts or prompts. What to
keep and in what order is decided above it.
"""

from videokit.edit import MAX_EDIT_BYTES, build_edit, edit_bytes, output_length
from videokit.errors import (
    MediaToolError,
    VideoAuthError,
    VideoError,
    VideoRejected,
    VideoTemporaryError,
)
from videokit.media import (
    extract_audio,
    frames,
    frames_at,
    prepare,
    probe,
    scene_changes,
)
from videokit.models import (
    AspectRatio,
    AudioTreatment,
    Brand,
    CaptionLine,
    CaptionWord,
    ComponentUse,
    Cut,
    EditSpec,
    Environment,
    Frame,
    Layout,
    LayoutSpan,
    MediaInfo,
    Motion,
    Overlay,
    RenderState,
    Resolution,
    Source,
    TextPosition,
    Transition,
    Zone,
)
from videokit.shotstack import Shotstack

__all__ = [
    "MAX_EDIT_BYTES",
    "AspectRatio",
    "AudioTreatment",
    "Brand",
    "CaptionLine",
    "CaptionWord",
    "ComponentUse",
    "Cut",
    "EditSpec",
    "Environment",
    "Frame",
    "Layout",
    "LayoutSpan",
    "MediaInfo",
    "MediaToolError",
    "Motion",
    "Overlay",
    "RenderState",
    "Resolution",
    "Shotstack",
    "Source",
    "TextPosition",
    "Transition",
    "VideoAuthError",
    "VideoError",
    "VideoRejected",
    "VideoTemporaryError",
    "Zone",
    "build_edit",
    "edit_bytes",
    "extract_audio",
    "frames",
    "frames_at",
    "output_length",
    "prepare",
    "probe",
    "scene_changes",
]
