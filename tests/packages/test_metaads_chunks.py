"""A video that goes to Meta in pieces, and the ways that can stop.

The subject is not really the upload - it is the bookkeeping around it.
Meta decides how big each piece is, the caller has to send exactly the
bytes between two offsets, and a session that is picked up again must not
produce a second video. Each of those is one wrong line away from an
upload that appears to work and leaves an unplayable file in somebody's ad
account.
"""

import re
from io import BytesIO
from typing import Any

import httpx
import pytest
from adskit.refs import ExternalRef
from metaads.assets import MetaAssets
from metaads.chunks import (
    CHUNKED_ABOVE_BYTES,
    VideoSession,
    cancel_chunked_video,
    upload_video_in_chunks,
)
from metaads.client import GraphClient
from metaads.errors import MetaAPIError

ACCOUNT = ExternalRef(provider="meta", level="account", id="act_1")

# One part of a multipart body: its name, and everything up to the next
# boundary. Enough for a test - the bodies here have at most four fields.
_PART = re.compile(
    rb'name="([^"]+)"(?:; filename="[^"]*")?\r\n'
    rb"(?:Content-Type: [^\r\n]+\r\n)?\r\n"
    rb"(.*?)\r\n--",
    re.DOTALL,
)


def fields(request: httpx.Request) -> dict[str, bytes]:
    """What one request said, whether it was form-encoded or multipart."""
    if b"multipart/form-data" in request.headers.get("content-type", "").encode():
        return {name.decode(): value for name, value in _PART.findall(request.content)}
    return {
        key: value.encode()
        for key, value in (
            pair.split("=", 1)
            for pair in request.content.decode().split("&")
            if "=" in pair
        )
    }


class FakeMeta:
    """Meta's half of a chunked upload, with a chunk size of its own choosing."""

    def __init__(self, *, size: int, chunk: int) -> None:
        self.size = size
        self.chunk = chunk
        self.received = b""
        self.calls: list[dict[str, bytes]] = []
        self.finished = False

    def client(self) -> GraphClient:
        return GraphClient(
            token="t", client=httpx.Client(transport=httpx.MockTransport(self))
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        sent = fields(request)
        self.calls.append(sent)
        phase = sent.get("upload_phase", b"").decode()

        if phase == "start":
            return httpx.Response(
                200,
                json={
                    "upload_session_id": "sess-1",
                    "video_id": "vid-9",
                    "start_offset": "0",
                    "end_offset": str(min(self.chunk, self.size)),
                },
            )
        if phase == "transfer":
            # The offset is absolute, not "everything this fake has been
            # handed": a resumed session starts part way through the file,
            # and a fake that counted its own bytes would answer with an
            # offset that had gone backwards.
            piece = sent["video_file_chunk"]
            self.received += piece
            start = int(sent["start_offset"]) + len(piece)
            return httpx.Response(
                200,
                json={
                    "start_offset": str(start),
                    "end_offset": str(min(start + self.chunk, self.size)),
                },
            )
        if phase == "finish":
            self.finished = True
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"success": True})

    def phases(self) -> list[str]:
        return [call.get("upload_phase", b"").decode() for call in self.calls]


def test_a_big_video_goes_as_a_session_and_arrives_whole() -> None:
    """Every byte, once, in order - and the id comes from the first call."""
    film = b"x" * 25
    meta = FakeMeta(size=len(film), chunk=10)

    created = upload_video_in_chunks(
        account_id="act_1",
        file=BytesIO(film),
        file_size=len(film),
        filename="reklama.mp4",
        token="t",
        client=meta.client(),
        dry_run=False,
    )

    assert created == "vid-9"
    assert meta.phases() == ["start", "transfer", "transfer", "transfer", "finish"]
    assert meta.received == film
    assert meta.finished


def test_the_pieces_are_the_ones_meta_asked_for() -> None:
    """Meta chooses the size; a caller that chose its own would be refused."""
    film = b"abcdefghij"
    meta = FakeMeta(size=len(film), chunk=4)

    upload_video_in_chunks(
        account_id="act_1",
        file=BytesIO(film),
        file_size=len(film),
        filename="a.mp4",
        token="t",
        client=meta.client(),
        dry_run=False,
    )

    transfers = [call for call in meta.calls if call.get("upload_phase") == b"transfer"]
    assert [call["video_file_chunk"] for call in transfers] == [b"abcd", b"efgh", b"ij"]
    assert [call["start_offset"] for call in transfers] == [b"0", b"4", b"8"]


def test_the_name_travels_with_the_last_call_only() -> None:
    """``title`` is refused by the transfer phase and kept by ``finish``."""
    meta = FakeMeta(size=4, chunk=4)

    upload_video_in_chunks(
        account_id="act_1",
        file=BytesIO(b"abcd"),
        file_size=4,
        filename="osh.mp4",
        token="t",
        client=meta.client(),
        dry_run=False,
    )

    assert meta.calls[-1]["title"] == b"osh.mp4"
    assert not any(
        b"osh.mp4" in call.get("video_file_chunk", b"") for call in meta.calls
    )


def test_an_interrupted_upload_carries_on_instead_of_starting_again() -> None:
    """The whole reason the upload task is allowed to retry.

    A second attempt that opened a second session would leave two videos in
    the ad account, one of them half a file.
    """
    film = b"0123456789"
    meta = FakeMeta(size=len(film), chunk=5)

    created = upload_video_in_chunks(
        account_id="act_1",
        file=BytesIO(film),
        file_size=len(film),
        filename="a.mp4",
        token="t",
        client=meta.client(),
        resume=VideoSession(
            session_id="sess-1", video_id="vid-9", start_offset=5, end_offset=10
        ),
        dry_run=False,
    )

    assert created == "vid-9"
    assert "start" not in meta.phases()
    assert meta.received == b"56789"


def test_a_session_that_only_failed_to_finish_is_finished() -> None:
    """Every byte arrived and the last word did not. Nothing is sent again."""
    meta = FakeMeta(size=10, chunk=5)

    upload_video_in_chunks(
        account_id="act_1",
        file=BytesIO(b"0123456789"),
        file_size=10,
        filename="a.mp4",
        token="t",
        client=meta.client(),
        resume=VideoSession(
            session_id="sess-1", video_id="vid-9", start_offset=10, end_offset=10
        ),
        dry_run=False,
    )

    assert meta.phases() == ["finish"]


def test_every_step_is_written_down_for_the_next_attempt() -> None:
    """Including the opening one: a worker that dies before the first piece
    has still created a video at Meta, and the session names it."""
    seen: list[VideoSession] = []
    meta = FakeMeta(size=10, chunk=5)

    upload_video_in_chunks(
        account_id="act_1",
        file=BytesIO(b"0123456789"),
        file_size=10,
        filename="a.mp4",
        token="t",
        client=meta.client(),
        remember=seen.append,
        dry_run=False,
    )

    assert [state.start_offset for state in seen] == [0, 5, 10]
    assert {state.session_id for state in seen} == {"sess-1"}
    assert {state.video_id for state in seen} == {"vid-9"}


def test_a_file_shorter_than_the_session_is_refused() -> None:
    """The file on disk is not the file the session was opened for. Sent
    anyway, it becomes a video Meta accepts and cannot play."""
    meta = FakeMeta(size=100, chunk=50)

    with pytest.raises(MetaAPIError):
        upload_video_in_chunks(
            account_id="act_1",
            file=BytesIO(b"short"),
            file_size=100,
            filename="a.mp4",
            token="t",
            client=meta.client(),
            dry_run=False,
        )


def test_meta_asking_for_the_same_piece_twice_stops_rather_than_loops() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        sent = fields(request)
        if sent.get("upload_phase") == b"start":
            return httpx.Response(
                200,
                json={
                    "upload_session_id": "s",
                    "video_id": "v",
                    "start_offset": "0",
                    "end_offset": "5",
                },
            )
        return httpx.Response(200, json={"start_offset": "0", "end_offset": "5"})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(MetaAPIError):
        upload_video_in_chunks(
            account_id="act_1",
            file=BytesIO(b"abcdefghij"),
            file_size=10,
            filename="a.mp4",
            token="t",
            client=graph,
            dry_run=False,
        )


def test_an_unreadable_offset_is_a_refusal_rather_than_nought() -> None:
    """Read as nought it would send the first piece again for ever."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"upload_session_id": "s", "video_id": "v", "end_offset": "5"}
        )

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(MetaAPIError):
        upload_video_in_chunks(
            account_id="act_1",
            file=BytesIO(b"abcde"),
            file_size=5,
            filename="a.mp4",
            token="t",
            client=graph,
            dry_run=False,
        )


def test_a_session_meta_would_not_name_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"start_offset": "0", "end_offset": "5"})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(MetaAPIError):
        upload_video_in_chunks(
            account_id="act_1",
            file=BytesIO(b"abcde"),
            file_size=5,
            filename="a.mp4",
            token="t",
            client=graph,
            dry_run=False,
        )


def test_a_video_meta_did_not_assemble_is_not_a_video() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        sent = fields(request)
        if sent.get("upload_phase") == b"start":
            return httpx.Response(
                200,
                json={
                    "upload_session_id": "s",
                    "video_id": "v",
                    "start_offset": "0",
                    "end_offset": "0",
                },
            )
        return httpx.Response(200, json={"success": False})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(MetaAPIError):
        upload_video_in_chunks(
            account_id="act_1",
            file=BytesIO(b""),
            file_size=0,
            filename="a.mp4",
            token="t",
            client=graph,
            dry_run=False,
        )


def test_a_dry_run_sends_nothing_and_reads_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a rehearsal called Meta")

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    assert upload_video_in_chunks(
        account_id="act_1",
        file=BytesIO(b"abc"),
        file_size=3,
        filename="a.mp4",
        token="t",
        client=graph,
    )


def test_a_session_nobody_will_finish_is_cancelled_quietly() -> None:
    """It runs after something else has already gone wrong, so a failure
    here must not replace the reason the caller is here."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "no", "code": 100}})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    cancel_chunked_video(
        account_id="act_1", session_id="sess-1", token="t", client=graph
    )


# --- The size that decides the route -------------------------------------
def routes(*, size: int, resume: VideoSession | None = None) -> str:
    """Which shape the adapter picked for a file of this size."""
    taken: list[str] = []

    def as_session(**kwargs: Any) -> str:
        taken.append("session")
        return "vid-9"

    def as_one_request(**kwargs: Any) -> str:
        taken.append("one")
        return "vid-9"

    assets = MetaAssets()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("metaads.assets.upload_video_in_chunks", as_session)
        patch.setattr("metaads.assets.upload_video", as_one_request)
        assets.upload_video(
            account=ACCOUNT,
            file=BytesIO(b""),
            file_size=size,
            filename="a.mp4",
            token="t",
            resume=resume,
            dry_run=False,
        )
    return taken[0]


def test_a_file_small_enough_for_one_request_goes_in_one_request() -> None:
    assert routes(size=CHUNKED_ABOVE_BYTES) == "one"


def test_a_file_past_the_ceiling_goes_as_a_session() -> None:
    """The ceiling is what an HTTP 413 with an empty body costs: a failed
    upload in front of a customer, against two extra round trips."""
    assert routes(size=CHUNKED_ABOVE_BYTES + 1) == "session"


def test_an_upload_that_has_already_begun_goes_back_to_its_session() -> None:
    """Whatever the size says. Starting again would create a second video."""
    begun = VideoSession(
        session_id="sess-1", video_id="vid-9", start_offset=2, end_offset=8
    )
    assert routes(size=8, resume=begun) == "session"
