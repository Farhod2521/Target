"""Speech to text, word by word.

Knows nothing about video, advertising or accounts: a recording goes in,
the words and their times come out.
"""

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
