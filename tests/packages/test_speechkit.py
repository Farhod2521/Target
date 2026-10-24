"""speechkit: what is sent to ElevenLabs and how the answer is read."""

import json
from pathlib import Path

import httpx
import pytest
from speechkit import ElevenLabs, SpeechAuthError, SpeechRejected, SpeechTemporaryError

ANSWER = {
    "language_code": "uzb",
    "text": "Salom do'stlar",
    "words": [
        {"text": "Salom", "start": 0.12, "end": 0.6, "type": "word"},
        {"text": " ", "start": 0.6, "end": 0.7, "type": "spacing"},
        {"text": "(kulgi)", "start": 0.7, "end": 0.9, "type": "audio_event"},
        {"text": "do'stlar", "start": 0.9, "end": 1.4, "type": "word"},
    ],
}


def _client(handler: httpx.MockTransport) -> ElevenLabs:
    return ElevenLabs(api_key="k", http=httpx.Client(transport=handler))


def test_only_words_come_back_each_with_its_times(tmp_path: Path) -> None:
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"sound")
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200, json=ANSWER)

    transcript = _client(httpx.MockTransport(answer)).transcribe(
        path=audio, language="uz"
    )

    assert [(w.text, w.start, w.end) for w in transcript.words] == [
        ("Salom", 0.12, 0.6),
        ("do'stlar", 0.9, 1.4),
    ]
    assert transcript.language == "uzb" and not transcript.silent
    body = seen[0].content
    assert seen[0].headers["xi-api-key"] == "k"
    assert b'name="model_id"' in body and b"scribe_v2" in body
    assert b'name="language_code"' in body and b"sound" in body


def test_a_recording_with_no_words_is_silent(tmp_path: Path) -> None:
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    handler = httpx.MockTransport(lambda r: httpx.Response(200, json={"words": []}))

    assert _client(handler).transcribe(path=audio).silent


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, SpeechAuthError),
        (429, SpeechTemporaryError),
        (500, SpeechTemporaryError),
        (422, SpeechRejected),
    ],
)
def test_refusals_become_three_errors(
    tmp_path: Path, status: int, error: type[Exception]
) -> None:
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    handler = httpx.MockTransport(lambda r: httpx.Response(status, json={}))

    with pytest.raises(error):
        _client(handler).transcribe(path=audio)


def test_an_empty_key_is_refused() -> None:
    with pytest.raises(SpeechAuthError):
        ElevenLabs(api_key="")


def test_a_sound_is_asked_for_by_its_description_and_comes_back_as_mp3() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200, content=b"ID3mp3")

    sound = _client(httpx.MockTransport(answer)).sound_effect(
        text="a soft pop", seconds=0.6
    )

    assert sound == b"ID3mp3"
    request = seen[0]
    assert request.url.path == "/v1/sound-generation"
    assert request.url.params["output_format"] == "mp3_44100_128"
    assert request.headers["xi-api-key"] == "k"
    body = json.loads(request.content)
    assert body == {
        "text": "a soft pop",
        "duration_seconds": 0.6,
        "prompt_influence": 0.5,
        "model_id": "eleven_text_to_sound_v2",
    }


def test_a_refused_sound_is_a_rejection() -> None:
    client = _client(
        httpx.MockTransport(lambda _: httpx.Response(422, json={"detail": []}))
    )

    with pytest.raises(SpeechRejected, match="sound: HTTP 422"):
        client.sound_effect(text="x", seconds=1)


def _sent(tmp_path: Path, **asked: object) -> bytes:
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"sound")
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200, json=ANSWER)

    _client(httpx.MockTransport(answer)).transcribe(path=audio, **asked)  # type: ignore[arg-type]
    return seen[0].content


def test_keyterms_go_as_the_field_repeated_once_per_term(tmp_path: Path) -> None:
    body = _sent(tmp_path, keyterms=("Chilonzor Fitnes", "CrossFit"))

    assert body.count(b'name="keyterms"') == 2
    assert b"Chilonzor Fitnes" in body and b"CrossFit" in body


def test_without_keyterms_none_are_sent(tmp_path: Path) -> None:
    """They cost a fifth more: no field when there is nothing to expect."""
    assert b'name="keyterms"' not in _sent(tmp_path)
    assert b'name="keyterms"' not in _sent(tmp_path, keyterms=("  ", "[]"))


def test_keyterms_the_api_would_refuse_are_left_out() -> None:
    from speechkit import usable_keyterms

    kept = usable_keyterms(
        [
            "Bahor kafesi",
            "bahor  KAFESI",  # the same, spelled again
            "Osh <Markazi>",  # refused characters dropped, the words kept
            "x" * 50,  # 50 characters: the limit is under 50
            "bir ikki uch tort besh olti",  # six words
            "",
            *[f"so'z{n}" for n in range(200)],
        ]
    )

    assert kept[:2] == ("Bahor kafesi", "Osh Markazi")
    assert len(kept) == 100
    assert all(len(term) < 50 and len(term.split()) <= 5 for term in kept)
