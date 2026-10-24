"""ElevenLabs: a recording in, the words and their times out - and, once
in a while, a short sound made from a description.

One request, answered when the transcript is done. The file travels in the
request body, so a machine with no public address can use it too.

Only words come back. Scribe also reports the gaps between words and
sounds such as laughter as entries of their own; a caller cutting a video
by its speech wants the words, and the gaps are what lies between them.
"""

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import httpx

from speechkit.errors import SpeechAuthError, SpeechRejected, SpeechTemporaryError
from speechkit.models import Transcript, Word

URL: Final = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL: Final = "scribe_v2"
SOUND_URL: Final = "https://api.elevenlabs.io/v1/sound-generation"
SOUND_MODEL: Final = "eleven_text_to_sound_v2"
SOUND_FORMAT: Final = "mp3_44100_128"
# A ten-minute recording is transcribed in well under a minute; the rest is
# the upload. Generous, because the alternative is paying for a transcript
# and closing the connection before it arrives.
DEFAULT_TIMEOUT_SECONDS: Final = 600.0

# Keyterm limits, from the API reference: each under 50 characters and
# five words, none of < > { } [ ] \ in it. More than 100 makes every
# request billed as at least 20 seconds.
KEYTERM_CHARS: Final = 50
KEYTERM_WORDS: Final = 5
MAX_KEYTERMS: Final = 100
_REFUSED: Final = re.compile(r"[<>{}\[\]\\]")

_AUTH: Final = frozenset({401, 403})
_BUSY: Final = frozenset({408, 409, 425, 429})
_REASON_CHARS: Final = 300


class ElevenLabs:
    """One account's key, ready to transcribe."""

    def __init__(
        self,
        *,
        api_key: str,
        http: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        model: str = MODEL,
    ) -> None:
        if not api_key:
            raise SpeechAuthError("ElevenLabs API key is empty")
        self._key = api_key
        self._http = http
        self._timeout = timeout
        self._model = model

    def transcribe(
        self, *, path: Path, language: str = "", keyterms: Sequence[str] = ()
    ) -> Transcript:
        """The words in a recording. ``language`` helps; empty lets it guess.

        ``keyterms`` are words to expect - a brand's name, its products -
        which Scribe v2 then spells as given when the context fits. Any the
        API would refuse are left out (:func:`usable_keyterms`). Asking
        with them costs a fifth more.
        """
        fields: dict[str, str | list[str]] = {
            "model_id": self._model,
            "timestamps_granularity": "word",
            "tag_audio_events": "false",
        }
        if language:
            fields["language_code"] = language
        if terms := usable_keyterms(keyterms):
            # A list in a form is the field repeated, once per term.
            fields["keyterms"] = list(terms)
        try:
            with path.open("rb") as handle:
                reply = self._post(fields=fields, upload=(path.name, handle))
        except OSError as exc:
            raise SpeechRejected(f"cannot read {path.name}") from exc
        except httpx.HTTPError as exc:
            raise SpeechTemporaryError(f"transcribe: {type(exc).__name__}") from exc
        _raise_for(reply, what="transcribe")
        try:
            payload = reply.json()
        except ValueError as exc:
            raise SpeechTemporaryError("transcribe: answer was not JSON") from exc
        return _transcript(payload if isinstance(payload, dict) else {})

    def sound_effect(
        self, *, text: str, seconds: float, prompt_influence: float = 0.5
    ) -> bytes:
        """An MP3 of the sound ``text`` describes, ``seconds`` long (0.5-30)."""
        body = {
            "text": text,
            "duration_seconds": seconds,
            "prompt_influence": prompt_influence,
            "model_id": SOUND_MODEL,
        }
        headers = {"xi-api-key": self._key, "Accept": "audio/mpeg"}
        try:
            with self._client() as client:
                reply = client.post(
                    SOUND_URL,
                    params={"output_format": SOUND_FORMAT},
                    headers=headers,
                    json=body,
                    timeout=self._timeout,
                )
        except httpx.HTTPError as exc:
            raise SpeechTemporaryError(f"sound: {type(exc).__name__}") from exc
        _raise_for(reply, what="sound")
        return reply.content

    @contextmanager
    def _client(self) -> Iterator[httpx.Client]:
        if self._http is not None:
            yield self._http
            return
        with httpx.Client() as client:
            yield client

    def _post(
        self, *, fields: dict[str, str | list[str]], upload: tuple[str, Any]
    ) -> httpx.Response:
        headers = {"xi-api-key": self._key, "Accept": "application/json"}
        with self._client() as client:
            return client.post(
                URL,
                headers=headers,
                data=fields,
                files={"file": upload},
                timeout=self._timeout,
            )


def usable_keyterms(terms: Sequence[str]) -> tuple[str, ...]:
    """``terms`` as the API takes them: each under :data:`KEYTERM_CHARS`
    characters and at most :data:`KEYTERM_WORDS` words, none of the
    characters it refuses, no repeats, at most :data:`MAX_KEYTERMS`.

    Over a hundred, every request is billed as at least twenty seconds;
    the cap keeps short clips at their own length.
    """
    kept: list[str] = []
    seen: set[str] = set()
    for raw in terms:
        term = " ".join(_REFUSED.sub(" ", raw).split())
        if (
            not term
            or len(term) >= KEYTERM_CHARS
            or len(term.split()) > KEYTERM_WORDS
            or term.casefold() in seen
        ):
            continue
        seen.add(term.casefold())
        kept.append(term)
    return tuple(kept[:MAX_KEYTERMS])


def _transcript(payload: dict[str, Any]) -> Transcript:
    words: list[Word] = []
    for item in payload.get("words") or []:
        if not isinstance(item, dict) or item.get("type", "word") != "word":
            continue
        text = str(item.get("text") or "").strip()
        start, end = item.get("start"), item.get("end")
        if not text or not isinstance(start, int | float):
            continue
        finish = end if isinstance(end, int | float) else start
        words.append(Word(text=text, start=float(start), end=float(max(finish, start))))
    return Transcript(
        language=str(payload.get("language_code") or ""),
        text=str(payload.get("text") or ""),
        words=tuple(words),
    )


def _raise_for(reply: httpx.Response, *, what: str) -> None:
    status = reply.status_code
    if status < 400:
        return
    reason = f"{what}: HTTP {status} {reply.text[:_REASON_CHARS]}".strip()
    if status in _AUTH:
        raise SpeechAuthError(reason)
    if status in _BUSY or status >= 500:
        raise SpeechTemporaryError(reason)
    raise SpeechRejected(reason)
