"""A video too big for one request, in the pieces Meta asks for.

:func:`metaads.uploads.upload_video` sends the whole file as one multipart
body, and above a certain size that body is refused outright - an HTTP 413
with an empty response, so the only thing known about the failure is its
status. Meta's answer to that is not a bigger request but a different
shape: a session, then the file in pieces, then a word to say it is over.

**Meta decides the size of each piece, not us.** The ``start`` phase
answers with the first ``start_offset`` and ``end_offset``, and every
``transfer`` answers with the next pair; a caller that chose its own chunk
size would be refused for sending bytes at an offset nobody asked for.
That is also what makes the loop below terminate: the offsets meet when
the file has arrived.

Three things follow from the session that are worth the extra module:

- **The video id exists before the bytes do.** ``start`` issues it, so a
  transfer that dies has still created an object at Meta - which is why
  :func:`cancel_chunked_video` exists and why the caller is handed the
  session rather than only the finished id.
- **A retry resumes instead of duplicating.** A whole-file upload that is
  tried twice creates two videos; a session that is tried twice carries on
  from the offset Meta last asked for. This is the only reason the upload
  task may retry at all.
- **Nothing of the file is ever held.** Each piece is read from the handle
  and dropped, so a two hundred megabyte video costs one chunk of memory
  rather than two hundred megabytes of it.
"""

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

# Above this a video goes in pieces. Well under the size Meta has been seen
# to refuse, because the cost of being wrong is not symmetric: a small file
# sent in one piece that gets a 413 is a failed upload in front of a
# customer, and a small file sent in three pieces is two extra round trips.
CHUNKED_ABOVE_BYTES: Final = 25 * 1024 * 1024

# The multipart part one piece travels in, and Meta's own name for it.
_CHUNK_FIELD: Final = "video_file_chunk"
_CHUNK_MIME: Final = "application/octet-stream"

_START: Final = "start"
_TRANSFER: Final = "transfer"
_FINISH: Final = "finish"
_CANCEL: Final = "cancel"


@dataclass(frozen=True, slots=True)
class VideoSession:
    """Where a chunked upload has got to, and what Meta wants next.

    ``video_id`` is issued by the first call rather than the last, so this
    names a real object at Meta from the moment the session opens. The two
    offsets are what to send next; when they meet, everything has arrived.
    """

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
    """Send one video as a session and return its id.

    ``resume`` carries a session an earlier attempt opened: passed, nothing
    already at Meta is sent again and no second video is created. ``None``
    opens a new one.

    ``remember`` is called with every session state this reaches, including
    the one the opening call answers with. It is how the caller survives its
    own death: a worker killed mid-transfer leaves the session id and the
    offset written down, and the next attempt hands them back as ``resume``.
    Without it this still works and a crash costs the whole file.
    """
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
    """Every piece Meta asks for, until it stops asking.

    **A transfer that does not move the offset raises.** Meta answering the
    same pair twice is not a slow upload, it is a loop, and a loop here is a
    worker reading the same megabyte until the queue dies.
    """
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
    """The bytes between two offsets, or a refusal to send a short piece.

    A read that comes back short means the file on disk is not the file the
    session was opened for - truncated, replaced, or a length somebody
    passed rather than measured. Sending it anyway produces a video Meta
    accepts and cannot play.
    """
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
    """One piece, and the offsets of the next one.

    The piece goes as multipart and everything else as ordinary fields,
    which is the shape Meta's own example uses. The session and the video id
    are carried forward untouched - only the offsets move.
    """
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
    """Tell Meta the file is whole. Until this, the video does not exist.

    ``title`` is what the ad account's library will call the row, and it is
    only accepted here: the transfer phase refuses every field that is not
    about the bytes.
    """
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
    """Give up on a session, for the caller that has stopped retrying.

    Logged rather than raised. This runs while something else has already
    gone wrong, and a failure to tidy up must not replace the reason the
    caller is here - what is left behind is an unfinished video nothing
    refers to.
    """
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
    """One offset, which Meta sends as a string of digits.

    A missing or unreadable one is a refusal rather than a nought: read as
    nought it would send the first piece again for ever.
    """
    raw = str(payload.get(field, "")).strip()
    if not raw.isdigit():
        raise MetaAPIError(f"Meta sent no readable {field}")
    return int(raw)
