"""Speech to text, word by word."""

from speechkit.elevenlabs import ElevenLabs, usable_keyterms
from speechkit.errors import (
    SpeechAuthError,
    SpeechError,
    SpeechRejected,
    SpeechTemporaryError,
)
from speechkit.models import Transcript, Word

__all__ = [
    "ElevenLabs",
    "SpeechAuthError",
    "SpeechError",
    "SpeechRejected",
    "SpeechTemporaryError",
    "Transcript",
    "Word",
    "usable_keyterms",
]
