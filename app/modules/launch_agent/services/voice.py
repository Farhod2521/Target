"""A spoken message into words.

The page records, sends the recording here and gets the words back to put
in the message box: the person reads them, mends what was misheard, and
sends them as any other message. Nothing is sent on their behalf.

The business's own names - what it is called, what it sells - go along as
key terms, since those are the words a recogniser gets wrong.
"""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from speechkit import (
    ElevenLabs,
    SpeechAuthError,
    SpeechRejected,
    SpeechTemporaryError,
    Transcript,
)
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.throttle import hit
from app.modules.businesses.models import Business
from app.modules.businesses.selectors.knowledge import known
from app.modules.launch_agent.constants import (
    MAX_TEXT_CHARS,
    VOICE_BUCKET,
    VOICE_LANGUAGES,
    VOICE_MAX_BYTES,
    VOICE_PER_DAY,
    VOICE_TIMEOUT_SECONDS,
)
from app.modules.launch_agent.exceptions import (
    VoiceBusy,
    VoiceLimit,
    VoiceOff,
    VoiceRefused,
    VoiceSilent,
    VoiceTooBig,
)
from app.modules.launch_agent.models import LaunchAgentSession

logger = logging.getLogger(__name__)

DAY_SECONDS: Final = 86400
MEGABYTE: Final = 1024 * 1024
_SUFFIXES: Final = frozenset(
    {".webm", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".mp3", ".wav", ".aac"}
)


@dataclass(frozen=True, slots=True)
class Spoken:
    """What was said, and the language it was heard as."""

    text: str
    language: str = ""


def keyterms(db: Session, session: LaunchAgentSession) -> tuple[str, ...]:
    """The names this business would say: its own and what it sells."""
    business = db.get(Business, session.business_id) if session.business_id else None
    if business is None:
        return ()
    view = known(db, business)
    names = [view.profile.name or ""]
    names += [str(item.get("name") or "") for item in view.active_items]
    return tuple(name for name in names if name.strip())


def _suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in _SUFFIXES else ".webm"


def _transcribe(
    data: bytes, *, filename: str, language: str, terms: tuple[str, ...]
) -> Transcript:
    key = settings.elevenlabs_voice_api_key
    if not key:
        raise VoiceOff
    with tempfile.NamedTemporaryFile(suffix=_suffix(filename)) as handle:
        handle.write(data)
        handle.flush()
        try:
            return ElevenLabs(api_key=key, timeout=VOICE_TIMEOUT_SECONDS).transcribe(
                path=Path(handle.name), language=language, keyterms=terms
            )
        except SpeechAuthError as exc:
            logger.error("launch_agent_voice_key_refused")
            raise VoiceOff from exc
        except SpeechTemporaryError as exc:
            logger.warning("launch_agent_voice_busy: %s", exc)
            raise VoiceBusy from exc
        except SpeechRejected as exc:
            logger.warning("launch_agent_voice_refused: %s", exc)
            raise VoiceRefused from exc


def to_text(
    db: Session,
    *,
    session: LaunchAgentSession,
    data: bytes,
    filename: str = "",
    language: str = "",
) -> Spoken:
    """The words in one recording, cut to what a message may hold."""
    if not settings.elevenlabs_voice_api_key:
        raise VoiceOff
    if not data:
        raise VoiceSilent
    if len(data) > VOICE_MAX_BYTES:
        raise VoiceTooBig(VOICE_MAX_BYTES // MEGABYTE)
    if not hit(
        bucket=VOICE_BUCKET,
        key=str(session.owner_id),
        limit=VOICE_PER_DAY,
        window_seconds=DAY_SECONDS,
    ):
        raise VoiceLimit
    heard = _transcribe(
        data,
        filename=filename,
        language=language if language in VOICE_LANGUAGES else "",
        terms=keyterms(db, session),
    )
    text = " ".join(heard.text.split())[:MAX_TEXT_CHARS]
    if heard.silent or not text:
        raise VoiceSilent
    return Spoken(text=text, language=heard.language)


__all__ = ["Spoken", "keyterms", "to_text"]
