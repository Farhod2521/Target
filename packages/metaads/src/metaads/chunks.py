"""A video too big for one request, in the pieces Meta asks for."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Final

from metaads.client import GraphClient
from metaads.errors import MetaAPIError
from metaads.uploads import Readable
from metaads.writing import fake_id, graph_client

logger = logging.getLogger(__name__)

_VIDEO: Final = "video"

CHUNKED_ABOVE_BYTES: Final = 25 * 1024 * 1024

_CHUNK_FIELD: Final = "video_file_chunk"
_CHUNK_MIME: Final = "application/octet-stream"

_START: Final = "start"
_TRANSFER: Final = "transfer"
_FINISH: Final = "finish"
_CANCEL: Final = "cancel"


@dataclass(frozen=True, slots=True)
class VideoSession:
    """Where a chunked upload has got to, and what Meta wants next."""

    session_id: str
    video_id: str
    start_offset: int
    end_offset: int

    @property
    def done(self) -> bool:
        """Whether Meta is still asking for bytes."""
        return self.start_offset >= self.end_offset


def upload_video_in_chunks(
    *,
    account_id: str,
    file: Readable,
    file_size: int,
    filename: str,
    token: str,
    client: GraphClient | None = None,
    resume: VideoSession | None = None,
    remember: Callable[[VideoSession], None] | None = None,
    dry_run: bool = True,
) -> str:
    """Send one video as a session and return its id."""
    if dry_run:
        return fake_id(_VIDEO)

    with graph_client(client, token) as graph:
        session = resume or start_chunked_video(
            account_id=account_id, file_size=file_size, token=token, client=graph
        )
        if resume is None and remember is not None:
            remember(session)

        session = _transfer_all(
            account_id=account_id,
            file=file,
            session=session,
            token=token,
            graph=graph,
            remember=remember,
        )
        finish_chunked_video(
            account_id=account_id,
            session=session,
            filename=filename,
            token=token,
            client=graph,
        )
    return session.video_id


def _transfer_all(
    *,
    account_id: str,
    file: Readable,
    session: VideoSession,
    token: str,
    graph: GraphClient,
    remember: Callable[[VideoSession], None] | None,
) -> VideoSession:
    """Every piece Meta asks for, until it stops asking."""
    while not session.done:
        chunk = _read_at(file=file, start=session.start_offset, end=session.end_offset)
        moved = send_chunk(
            account_id=account_id,
            session=session,
            chunk=chunk,
            token=token,
            client=graph,
        )
        if moved.start_offset <= session.start_offset and not moved.done:
            raise MetaAPIError(
                f"Meta asked for the same piece twice at {session.start_offset}"
            )
        session = moved
        if remember is not None:
            remember(session)
    return session


def _read_at(*, file: Readable, start: int, end: int) -> bytes:
    """The bytes between two offsets, or a refusal to send a short piece."""
    file.seek(start)
    chunk = file.read(end - start)
    if len(chunk) != end - start:
        raise MetaAPIError(
            f"the file has {len(chunk)} bytes where Meta asked for {end - start}"
        )
    return chunk


def start_chunked_video(
    *, account_id: str, file_size: int, token: str, client: GraphClient | None = None
) -> VideoSession:
    """Open the session. Meta issues the video id here, before any bytes."""
    with graph_client(client, token) as graph:
        payload = graph.post(
            f"{account_id}/advideos", upload_phase=_START, file_size=file_size
        )

    session_id = str(payload.get("upload_session_id", ""))
    video_id = str(payload.get("video_id", ""))
    if not session_id or not video_id:
        raise MetaAPIError("Meta opened an upload session without naming it")

    return VideoSession(
        session_id=session_id,
        video_id=video_id,
        start_offset=_offset(payload, "start_offset"),
        end_offset=_offset(payload, "end_offset"),
    )


def send_chunk(
    *,
    account_id: str,
    session: VideoSession,
    chunk: bytes,
    token: str,
    client: GraphClient | None = None,
) -> VideoSession:
    """One piece, and the offsets of the next one."""
    with graph_client(client, token) as graph:
        payload = graph.upload(
            f"{account_id}/advideos",
            files={_CHUNK_FIELD: (_CHUNK_FIELD, chunk, _CHUNK_MIME)},
            upload_phase=_TRANSFER,
            upload_session_id=session.session_id,
            start_offset=session.start_offset,
        )

    return replace(
        session,
        start_offset=_offset(payload, "start_offset"),
        end_offset=_offset(payload, "end_offset"),
    )


def finish_chunked_video(
    *,
    account_id: str,
    session: VideoSession,
    filename: str,
    token: str,
    client: GraphClient | None = None,
) -> None:
    """Tell Meta the file is whole. Until this, the video does not exist."""
    with graph_client(client, token) as graph:
        payload = graph.post(
            f"{account_id}/advideos",
            upload_phase=_FINISH,
            upload_session_id=session.session_id,
            title=filename,
        )

    if payload.get("success") in (True, "true"):
        return
    raise MetaAPIError("Meta did not confirm the video was assembled")


def cancel_chunked_video(
    *,
    account_id: str,
    session_id: str,
    token: str,
    client: GraphClient | None = None,
) -> None:
    """Give up on a session, for the caller that has stopped retrying."""
    try:
        with graph_client(client, token) as graph:
            graph.post(
                f"{account_id}/advideos",
                upload_phase=_CANCEL,
                upload_session_id=session_id,
            )
    except MetaAPIError:
        logger.info("an upload session could not be cancelled")


def _offset(payload: dict[str, Any], field: str) -> int:
    """One offset, which Meta sends as a string of digits."""
    raw = str(payload.get(field, "")).strip()
    if not raw.isdigit():
        raise MetaAPIError(f"Meta sent no readable {field}")
    return int(raw)
