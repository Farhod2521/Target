"""The pictures step's uploads: pieces, the finished file, and the text gate."""

import io
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.ads.constants import UPLOAD_CHUNK_BYTES, MediaKind
from app.modules.ads.models import CampaignLaunch, LaunchCreative, MediaAsset
from tests.pg.test_launch_api import _ready


@pytest.fixture
def media_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    return tmp_path


def _at_media(client: TestClient, db: Session) -> tuple[dict[str, str], str]:
    auth, _user = _ready(client, db)
    launch_id = client.post("/api/v1/launch", headers=auth).json()["id"]
    plan = client.get(f"/api/v1/launch/{launch_id}/plan", headers=auth).json()
    goals = [item["goal"] for item in plan["goals"]]
    goal = "traffic" if "traffic" in goals else goals[0]
    fields = client.get(
        f"/api/v1/launch/{launch_id}/plan?goal={goal}", headers=auth
    ).json()
    saved = client.post(
        f"/api/v1/launch/{launch_id}/plan",
        json={
            "goal": goal,
            "daily_budget": fields["initial"]["daily_budget"] or "10",
            "link_url": "bahor.example",
            "phone_number": "+998901234567",
            "welcome_text": "Salom!",
            "start_day": "tomorrow",
        },
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    return auth, launch_id


def _picture() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1080, 1080), "white").save(out, format="JPEG")
    return out.getvalue()


def _send_in_pieces(
    client: TestClient, auth: dict[str, str], launch_id: str, data: bytes
) -> str:
    upload_id = str(uuid.uuid4())
    half = len(data) // 2
    for offset, piece in ((0, data[:half]), (half, data[half:])):
        sent = client.post(
            f"/api/v1/launch/{launch_id}/media/upload/chunk",
            content=piece,
            headers=auth
            | {
                "X-Upload-Id": upload_id,
                "X-Upload-Size": str(len(data)),
                "X-Upload-Offset": str(offset),
            },
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["offset"] == offset + len(piece)
    return upload_id


def _parts(root: Path) -> list[Path]:
    return list(root.rglob("*.part"))


def test_a_file_sent_in_pieces_leaves_no_piece_behind(
    client: TestClient, db: Session, queued: list, media_root: Path
) -> None:
    auth, launch_id = _at_media(client, db)
    data = _picture()
    upload_id = _send_in_pieces(client, auth, launch_id, data)
    assert len(_parts(media_root)) == 1

    finished = client.post(
        f"/api/v1/launch/{launch_id}/media/upload/finish",
        json={"upload_id": upload_id, "total": len(data), "name": "osh.jpg"},
        headers=auth,
    )

    assert finished.status_code == 200, finished.text
    assert _parts(media_root) == []
    row = db.scalar(
        select(LaunchCreative).where(LaunchCreative.launch_id == uuid.UUID(launch_id))
    )
    assert row is not None and row.media_upload.startswith("launch-media/")
    assert (media_root / row.media_upload).read_bytes() == data
    assert any(name.endswith("upload_to_library_task") for name, _ in queued)


def test_a_refused_file_leaves_no_piece_behind(
    client: TestClient, db: Session, media_root: Path
) -> None:
    auth, launch_id = _at_media(client, db)
    data = _picture()
    upload_id = _send_in_pieces(client, auth, launch_id, data)

    refused = client.post(
        f"/api/v1/launch/{launch_id}/media/upload/finish",
        json={"upload_id": upload_id, "total": len(data), "name": "osh.exe"},
        headers=auth,
    )

    assert refused.status_code == 422
    assert _parts(media_root) == []


def test_a_piece_larger_than_a_piece_is_refused(
    client: TestClient, db: Session, media_root: Path
) -> None:
    auth, launch_id = _at_media(client, db)
    headers = auth | {
        "X-Upload-Id": str(uuid.uuid4()),
        "X-Upload-Size": str(UPLOAD_CHUNK_BYTES * 2),
        "X-Upload-Offset": "0",
    }
    url = f"/api/v1/launch/{launch_id}/media/upload/chunk"

    declared = client.post(
        url, content=b"x" * (UPLOAD_CHUNK_BYTES + 1), headers=headers
    )

    def undeclared() -> Iterator[bytes]:
        for _ in range(UPLOAD_CHUNK_BYTES // (1024 * 1024) + 1):
            yield b"x" * (1024 * 1024)

    streamed = client.post(url, content=undeclared(), headers=headers)

    for answer in (declared, streamed):
        assert answer.status_code == 413, answer.text
        assert answer.json()["code"] == "chunk_too_large"
    assert _parts(media_root) == []


def test_a_missing_text_keeps_the_tiles_ticked(
    client: TestClient, db: Session, media_root: Path
) -> None:
    auth, launch_id = _at_media(client, db)
    launch = db.get(CampaignLaunch, uuid.UUID(launch_id))
    assert launch is not None
    asset = MediaAsset(
        owner_id=launch.owner_id,
        ad_account_id=launch.ad_account_id,
        provider=launch.provider,
        kind=MediaKind.IMAGE,
        external_id="hash_1",
        name="osh.jpg",
        width=1080,
        height=1080,
    )
    db.add(asset)
    db.commit()

    refused = client.post(
        f"/api/v1/launch/{launch_id}/media",
        json={"asset_ids": [str(asset.id)], "text": {"mode": "each"}},
        headers=auth,
    )

    assert refused.status_code == 400, refused.text
    db.expire_all()
    kept = db.scalars(
        select(LaunchCreative).where(LaunchCreative.launch_id == launch.id)
    ).all()
    assert [row.media_asset_id for row in kept] == [asset.id]
    assert db.get(CampaignLaunch, launch.id).answers["text_mode"] == "each"
