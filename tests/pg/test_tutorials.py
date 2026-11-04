"""Video darsliklar: written in the office, watched in the cabinet in pieces."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.backoffice.constants import Role
from app.modules.tutorials.constants import STREAM_PIECE_BYTES
from app.modules.tutorials.models import Tutorial
from tests.pg.conftest import sign_up
from tests.pg.test_office_actions import _staff

OFFICE = "/api/v1/office/tutorials"
CABINET = "/api/v1/tutorials"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x02\x00\x00\x00\x02\x00"
    b"\x08\x02\x00\x00\x00" + b"\x00" * 64
)
# Bigger than one piece the viewer gets, so the stream has to be asked twice.
MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * (STREAM_PIECE_BYTES // 128)


@pytest.fixture(autouse=True)
def media_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    return tmp_path


def _form(**fields: Any) -> dict[str, str]:
    base = {
        "title": "Pikselni ulash",
        "type": "meta",
        "description": "Meta piksel qanday ulanadi",
        "video_url": "",
        "status": "true",
    }
    return {key: str(value) for key, value in (base | fields).items()}


def _upload(client: TestClient, headers: dict[str, str], data: bytes) -> str:
    upload_id = str(uuid.uuid4())
    half = len(data) // 2
    for offset, piece in ((0, data[:half]), (half, data[half:])):
        answer = client.post(
            f"{OFFICE}/uploads/chunk",
            headers=headers
            | {
                "X-Upload-Id": upload_id,
                "X-Upload-Size": str(len(data)),
                "X-Upload-Offset": str(offset),
            },
            content=piece,
        )
        assert answer.status_code == 200, answer.text
    return upload_id


def test_the_office_writes_and_only_shown_lessons_reach_the_cabinet(
    client: TestClient, db: Session, media_root: Path
) -> None:
    _, office = _staff(db, Role.SUPPORT, email="support@office.test")
    _, engineer = _staff(db, Role.ENGINEER, email="dev@office.test")
    customer = sign_up(client)

    assert client.post(OFFICE, headers=engineer, data=_form()).status_code == 404
    assert client.post(OFFICE, headers=customer, data=_form()).status_code == 404

    neither = client.post(OFFICE, headers=office, data=_form(title=" ", type="tiktok"))
    assert neither.status_code == 422
    assert set(neither.json()["problems"]) == {"title", "type", "video"}

    linked = client.post(
        OFFICE,
        headers=office,
        data=_form(video_url="https://youtu.be/dQw4w9WgXcQ"),
        files={"image": ("cover.png", PNG, "image/png")},
    )
    assert linked.status_code == 200, linked.text
    hidden = client.post(
        OFFICE,
        headers=office,
        data=_form(
            title="Google kampaniya",
            type="google",
            description="yashirin",
            video_url="https://vimeo.com/1",
            status="false",
        ),
    )
    assert hidden.status_code == 200, hidden.text

    shown = client.get(CABINET, headers=customer).json()
    assert [row["title"] for row in shown["rows"]] == ["Pikselni ulash"]
    video = shown["rows"][0]["video"]
    assert video == {
        "kind": "youtube",
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "embed_url": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    }
    cover = client.get(shown["rows"][0]["image_url"])
    assert cover.status_code == 200 and cover.content == PNG
    assert cover.headers["cache-control"] == "private, no-store"
    assert (
        client.get(f"{CABINET}/{hidden.json()['id']}", headers=customer).status_code
        == 404
    )

    everything = client.get(OFFICE, headers=office).json()
    assert everything["total"] == 2
    assert [
        row["title"]
        for row in client.get(
            OFFICE, headers=office, params={"status": "false"}
        ).json()["rows"]
    ] == ["Google kampaniya"]
    assert (
        client.get(OFFICE, headers=office, params={"type": "google"}).json()["total"]
        == 1
    )
    assert (
        client.get(OFFICE, headers=office, params={"q": "YASHIRIN"}).json()["total"]
        == 1
    )
    assert client.get(CABINET, headers=customer, params={"q": "%"}).json()["total"] == 0

    assert (
        client.patch(
            f"{OFFICE}/{hidden.json()['id']}/status",
            headers=office,
            json={"status": True},
        ).status_code
        == 200
    )
    assert client.get(CABINET, headers=customer).json()["total"] == 2
    assert (
        client.get(CABINET, headers=customer, params={"type": "google"}).json()["rows"][
            0
        ]["video"]["kind"]
        == "link"
    )


def test_an_uploaded_video_plays_one_piece_at_a_time(
    client: TestClient, db: Session, media_root: Path
) -> None:
    _, office = _staff(db, Role.OWNER, email="owner@office.test")
    customer = sign_up(client)
    upload_id = _upload(client, office, MP4)

    both = client.post(
        OFFICE,
        headers=office,
        data=_form(
            video_url="https://youtu.be/dQw4w9WgXcQ",
            video_upload_id=upload_id,
            video_size=len(MP4),
            video_name="dars.mp4",
        ),
    )
    assert both.status_code == 422
    assert set(both.json()["problems"]) == {"video_url"}

    made = client.post(
        OFFICE,
        headers=office,
        data=_form(
            video_upload_id=upload_id, video_size=len(MP4), video_name="dars.mp4"
        ),
    )
    assert made.status_code == 200, made.text
    row = db.get(Tutorial, uuid.UUID(made.json()["id"]))
    assert row is not None and row.video_file.startswith("tutorials/videos/")
    assert not list((media_root / "tutorials" / "partial").rglob("*.part"))

    stream = client.get(f"{CABINET}/{row.id}", headers=customer).json()["video"][
        "stream_url"
    ]
    whole = client.get(stream)
    assert whole.status_code == 206
    assert len(whole.content) == STREAM_PIECE_BYTES, "a plain GET is one piece"
    assert whole.headers["content-range"] == (
        f"bytes 0-{STREAM_PIECE_BYTES - 1}/{len(MP4)}"
    )
    played = whole.content
    while len(played) < len(MP4):
        piece = client.get(stream, headers={"Range": f"bytes={len(played)}-"})
        assert piece.status_code == 206
        assert len(piece.content) <= STREAM_PIECE_BYTES
        played += piece.content
    assert played == MP4
    tail = client.get(stream, headers={"Range": "bytes=-10"})
    assert tail.content == MP4[-10:]
    assert (
        client.get(stream, headers={"Range": f"bytes={len(MP4)}-"}).status_code == 416
    )
    assert client.get(stream.split("?")[0]).status_code == 422
    assert client.get(stream.replace("t=", "t=x")).status_code == 404
    other = client.get(stream.replace(str(row.id), str(uuid.uuid4())))
    assert other.status_code == 404, "a token opens its own lesson only"

    client.patch(f"{OFFICE}/{row.id}/status", headers=office, json={"status": False})
    assert client.get(stream).status_code == 404, "hidden stops the cabinet's link"
    office_stream = client.get(f"{OFFICE}/{row.id}", headers=office).json()["video"][
        "stream_url"
    ]
    assert client.get(office_stream).status_code == 206, "the office still plays it"

    moved = client.put(
        f"{OFFICE}/{row.id}",
        headers=office,
        data=_form(video_url="https://vimeo.com/2", remove_video="true"),
    )
    assert moved.status_code == 200, moved.text
    assert not list((media_root / "tutorials" / "videos").rglob("*.mp4"))

    assert client.delete(f"{OFFICE}/{row.id}", headers=office).status_code == 200
    row_id = row.id
    db.expire_all()
    assert db.get(Tutorial, row_id) is None


def test_a_file_that_is_not_a_video_is_refused(client: TestClient, db: Session) -> None:
    _, office = _staff(db, Role.FINANCE, email="finance@office.test")
    upload_id = _upload(client, office, b"not a video at all, honestly")
    refused = client.post(
        OFFICE,
        headers=office,
        data=_form(
            video_upload_id=upload_id,
            video_size=len(b"not a video at all, honestly"),
            video_name="dars.mp4",
        ),
    )
    assert refused.status_code == 422
    assert refused.json()["problems"] == {"video": "Bu fayl MP4 video emas."}
    mov = _upload(client, office, MP4)
    assert client.post(
        OFFICE,
        headers=office,
        data=_form(video_upload_id=mov, video_size=len(MP4), video_name="dars.mov"),
    ).json()["problems"] == {"video": "Faqat MP4, WEBM video yuklang."}
