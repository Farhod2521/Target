"""videokit: the edit JSON, the Shotstack calls, and FFmpeg on a real file.

No network: Shotstack is an ``httpx.MockTransport``. FFmpeg is the real
program when the machine has it - a stand-in would only test the
stand-in - and those tests are skipped where it is missing.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from videokit import (
    MAX_EDIT_BYTES,
    CaptionLine,
    CaptionWord,
    Cut,
    EditSpec,
    MediaToolError,
    Overlay,
    Shotstack,
    VideoAuthError,
    VideoRejected,
    VideoTemporaryError,
    build_edit,
    edit_bytes,
    extract_audio,
    frames,
    output_length,
    prepare,
    probe,
    scene_changes,
)

SOURCE = "https://example.test/source.mp4"


# --- The edit ------------------------------------------------------------
def test_cuts_play_back_to_back_each_trimmed_into_the_source() -> None:
    spec = EditSpec(
        source_url=SOURCE, cuts=(Cut(start=10, end=13.5), Cut(start=2, end=4))
    )

    footage = build_edit(spec)["timeline"]["tracks"][-1]["clips"]

    assert [(c["start"], c["length"], c["asset"]["trim"]) for c in footage] == [
        (0, 3.5, 10),
        (3.5, 2, 2),
    ]
    assert output_length(spec.cuts) == 5.5


def test_text_is_drawn_above_captions_above_footage_above_music() -> None:
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=5),),
        captions_url="https://example.test/c.srt",
        overlays=(Overlay(text="Chegirma 20%", start=0, length=2),),
        music_url="https://example.test/m.mp3",
    )

    tracks = build_edit(spec)["timeline"]["tracks"]

    kinds = [track["clips"][0]["asset"]["type"] for track in tracks]
    assert kinds == ["rich-text", "rich-caption", "video", "audio"]


def test_a_push_in_scales_its_clip_and_only_the_end_fades() -> None:
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=2), Cut(start=3, end=5, zoom=1.15), Cut(start=6, end=8)),
    )

    footage = build_edit(spec)["timeline"]["tracks"][-1]["clips"]

    assert [c.get("scale") for c in footage] == [None, 1.15, None]
    assert [c.get("transition") for c in footage] == [
        None,
        None,
        {"out": "fade"},
    ]


def test_nothing_optional_means_one_track_of_footage() -> None:
    edit = build_edit(EditSpec(source_url=SOURCE, cuts=(Cut(start=0, end=1),)))

    assert len(edit["timeline"]["tracks"]) == 1
    assert edit["output"] == {
        "format": "mp4",
        "resolution": "hd",
        "aspectRatio": "9:16",
        "fps": 30,
    }


def test_the_footage_is_cropped_to_the_frame_not_stretched() -> None:
    edit = build_edit(EditSpec(source_url=SOURCE, cuts=(Cut(start=0, end=1),)))

    assert edit["timeline"]["tracks"][0]["clips"][0]["fit"] == "crop"


def _line(*words: tuple[str, float, float]) -> CaptionLine:
    return CaptionLine(
        start=words[0][1],
        end=words[-1][2],
        words=tuple(CaptionWord(text=t, start=s, end=e) for t, s, e in words),
    )


def test_word_captions_share_one_html5_clip_and_beat_the_srt() -> None:
    """The brand's font is inlined once per clip, so lines in the same
    band go into one; each shows from its start to its stop."""
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=6),),
        captions=(
            _line(("Bugun", 0.5, 0.9), ("chegirma", 1.0, 1.6)),
            _line(("<b>20%</b>", 1.65, 2.2)),
        ),
        captions_url="https://example.test/c.srt",
    )

    clips = build_edit(spec)["timeline"]["tracks"][0]["clips"]

    assert [c["asset"]["type"] for c in clips] == ["html5"]
    assert (clips[0]["start"], clips[0]["length"]) == (0.5, 1.85)
    js = clips[0]["asset"]["js"]
    # The first line gives way the moment the second is due; each word is
    # lit from its own start, relative to the clip.
    assert '{"s": 0.0, "e": 1.15, "w": [0.0, 0.5]}' in js
    assert '{"s": 1.15, "e": 1.85, "w": [1.15]}' in js
    assert "color:'#ffd400'" in js
    assert clips[0]["asset"]["css"].count("@font-face") == 1
    # Words are text, never markup.
    assert "&lt;b&gt;20%&lt;/b&gt;" in clips[0]["asset"]["html"]


def test_sizes_are_drawn_for_the_frame_the_video_renders_at() -> None:
    def caption(resolution: str) -> dict[str, Any]:
        spec = EditSpec(
            source_url=SOURCE,
            cuts=(Cut(start=0, end=2),),
            resolution=resolution,  # type: ignore[arg-type]
            captions=(_line(("Salom", 0.0, 0.5)),),
        )
        return build_edit(spec)["timeline"]["tracks"][0]["clips"][0]

    full, small = caption("1080"), caption("hd")

    assert (full["width"], full["height"]) == (800, 220)
    assert (small["width"], small["height"]) == (534, 147)
    assert "font-size:68px" in full["asset"]["css"]
    assert "font-size:45px" in small["asset"]["css"]


def test_an_edit_measures_its_own_size_on_the_wire() -> None:
    edit = {"timeline": {"tracks": []}, "text": "Қ"}

    assert edit_bytes(edit) == len(json.dumps(edit).encode())
    assert edit_bytes(edit) < MAX_EDIT_BYTES


# --- The client ----------------------------------------------------------
class _Recorder:
    def __init__(self, *answers: httpx.Response) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return self.answers.pop(0)


def _client(recorder: _Recorder) -> Shotstack:
    http = httpx.Client(transport=httpx.MockTransport(recorder))
    return Shotstack(api_key="k", environment="stage", http=http)


def _json(body: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def test_an_upload_asks_for_a_signed_address_then_puts_the_file_there(
    tmp_path: Path,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video-bytes")
    recorder = _Recorder(
        _json(
            {"data": {"id": "src1", "attributes": {"url": "https://s3.test/put?sig=1"}}}
        ),
        httpx.Response(200),
    )

    source_id = _client(recorder).upload(path=clip)

    ask, put = recorder.requests
    assert source_id == "src1"
    assert ask.url.path == "/ingest/stage/upload"
    assert json.loads(ask.content) == {"filename": "clip.mp4"}
    assert ask.headers["x-api-key"] == "k"
    assert put.method == "PUT" and put.content == b"video-bytes"
    # S3 refuses a header its signature did not cover.
    assert "x-api-key" not in put.headers


@pytest.mark.parametrize(
    ("code", "error"),
    [("RequestTimeout", VideoTemporaryError), ("AccessDenied", VideoRejected)],
)
def test_a_dropped_upload_is_tried_again_and_a_refused_one_is_not(
    tmp_path: Path, code: str, error: type[Exception]
) -> None:
    """S3 answers a connection it gave up on with a 400 that says so."""
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video-bytes")
    recorder = _Recorder(
        _json(
            {"data": {"id": "src1", "attributes": {"url": "https://s3.test/put?sig=1"}}}
        ),
        httpx.Response(400, text=f"<Error><Code>{code}</Code></Error>"),
    )

    with pytest.raises(error):
        _client(recorder).upload(path=clip)


def test_a_source_reads_its_status_url_and_length() -> None:
    recorder = _Recorder(
        _json(
            {
                "data": {
                    "attributes": {
                        "status": "ready",
                        "source": "https://cdn.test/s.mp4",
                        "duration": 25.86,
                    }
                }
            }
        )
    )

    source = _client(recorder).source(source_id="src1")

    assert (source.status, source.url, source.duration) == (
        "ready",
        "https://cdn.test/s.mp4",
        25.86,
    )


def test_a_render_is_queued_and_its_state_read_back() -> None:
    recorder = _Recorder(
        _json({"success": True, "response": {"id": "r1"}}),
        _json({"response": {"status": "done", "url": "https://cdn.test/out.mp4"}}),
    )
    client = _client(recorder)

    render_id = client.render(edit={"timeline": {}})
    state = client.render_state(render_id=render_id)

    assert recorder.requests[0].url.path == "/edit/stage/render"
    assert recorder.requests[1].url.path == "/edit/stage/render/r1"
    assert state.finished and state.url == "https://cdn.test/out.mp4"


def test_a_finished_render_says_how_long_it_runs_and_took() -> None:
    recorder = _Recorder(
        _json({"response": {"status": "done", "duration": 28.4, "renderTime": 9120}})
    )

    state = _client(recorder).render_state(render_id="r1")

    assert (state.duration, state.render_ms) == (28.4, 9120)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, VideoAuthError),
        (429, VideoTemporaryError),
        (503, VideoTemporaryError),
        (400, VideoRejected),
    ],
)
def test_a_refusal_becomes_one_of_three_errors(
    status: int, error: type[Exception]
) -> None:
    recorder = _Recorder(_json({"message": "no"}, status=status))

    with pytest.raises(error):
        _client(recorder).render(edit={})


def test_a_dropped_connection_is_temporary() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    http = httpx.Client(transport=httpx.MockTransport(broken))
    with pytest.raises(VideoTemporaryError):
        Shotstack(api_key="k", environment="v1", http=http).render(edit={})


def test_an_empty_key_is_refused_before_any_request() -> None:
    with pytest.raises(VideoAuthError):
        Shotstack(api_key="", environment="stage")


def test_a_download_stops_at_its_budget_and_resumes_with_a_range(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out.mp4"
    out.write_bytes(b"finished ")
    recorder = _Recorder(httpx.Response(206, content=b"video"))

    complete = _client(recorder).download(url="https://cdn.test/o.mp4", to=out)

    assert complete
    assert recorder.requests[0].headers["Range"] == "bytes=9-"
    assert out.read_bytes() == b"finished video"


def test_a_download_out_of_time_says_so_and_keeps_what_arrived(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out.mp4"
    recorder = _Recorder(httpx.Response(200, content=b"part"))

    complete = _client(recorder).download(
        url="https://cdn.test/o.mp4", to=out, max_seconds=-1
    )

    assert not complete
    assert out.read_bytes() == b"part"


def test_a_file_already_whole_is_done_without_writing(tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    out.write_bytes(b"all of it")
    recorder = _Recorder(httpx.Response(416))

    assert _client(recorder).download(url="https://cdn.test/o.mp4", to=out)
    assert out.read_bytes() == b"all of it"


# --- FFmpeg --------------------------------------------------------------
needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="FFmpeg is not installed on this machine",
)


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    """Six seconds of test pattern with a tone under it."""
    path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


@needs_ffmpeg
def test_probe_reads_length_size_and_sound(sample: Path) -> None:
    info = probe(sample)

    assert 5.5 <= info.duration <= 6.5
    assert (info.width, info.height, info.has_audio) == (320, 240, True)


@needs_ffmpeg
def test_frames_are_taken_every_n_seconds_and_capped(sample: Path) -> None:
    stills = frames(sample, every=2, width=160, limit=2)

    assert [still.at for still in stills] == [0, 2]
    assert all(still.jpeg.startswith(b"\xff\xd8") for still in stills)


@needs_ffmpeg
def test_the_sound_is_taken_out_alone(sample: Path, tmp_path: Path) -> None:
    out = extract_audio(sample, to=tmp_path / "a.m4a")

    assert probe_has_no_picture(out)


@needs_ffmpeg
@pytest.mark.parametrize("audio", ["level", "voice"])
def test_preparing_keeps_picture_and_sound_and_treats_the_sound(
    sample: Path, tmp_path: Path, audio: Any
) -> None:
    out = prepare(sample, to=tmp_path / "clean.mp4", audio=audio)

    info = probe(out)
    assert 5.5 <= info.duration <= 6.5
    assert (info.width, info.height, info.has_audio) == (320, 240, True)


@needs_ffmpeg
def test_preparing_a_silent_file_leaves_it_silent(sample: Path, tmp_path: Path) -> None:
    out = prepare(sample, to=tmp_path / "quiet.mp4", audio="none")

    assert probe(out).has_audio is False


def probe_has_no_picture(path: Path) -> bool:
    with pytest.raises(MediaToolError, match="no picture"):
        probe(path)
    return True


def test_a_missing_program_says_so() -> None:
    with pytest.raises(MediaToolError, match="not installed"):
        probe(Path("x.mp4"), ffprobe="definitely-not-ffprobe")


@needs_ffmpeg
def test_a_change_of_shot_is_found_and_a_still_picture_is_not(tmp_path: Path) -> None:
    clip = tmp_path / "two_shots.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=blue:size=160x284:rate=10:duration=2",
         "-f", "lavfi", "-i", "color=c=yellow:size=160x284:rate=10:duration=2",
         "-filter_complex", "[0][1]concat=n=2:v=1", str(clip)],
        check=True,
    )  # fmt: skip
    still = tmp_path / "still.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "color=c=blue:size=160x284:rate=10:duration=3", str(still)],
        check=True,
    )  # fmt: skip

    assert scene_changes(clip) == [pytest.approx(2.0, abs=0.11)]
    assert scene_changes(still) == []
