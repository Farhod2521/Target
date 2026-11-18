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


def test_a_lesson_shows_on_the_screens_it_names(
    client: TestClient, db: Session
) -> None:
    _, office = _staff(db, Role.SUPPORT, email="places@office.test")
    customer = sign_up(client)

    wrong = client.post(
        OFFICE,
        headers=office,
        data=_form(video_url="https://youtu.be/dQw4w9WgXcQ")
        | {"places": ["crm", "kino"]},
    )
    assert wrong.status_code == 422
    assert set(wrong.json()["problems"]) == {"places"}

    made = client.post(
        OFFICE,
        headers=office,
        data=_form(video_url="https://youtu.be/dQw4w9WgXcQ")
        | {"places": ["leads", "crm", "crm"]},
    )
    assert made.status_code == 200, made.text
    plain = client.post(
        OFFICE,
        headers=office,
        data=_form(title="Faqat bo'limda", video_url="https://vimeo.com/3"),
    )
    assert plain.status_code == 200, plain.text
    lesson_id = made.json()["id"]

    one = client.get(f"{CABINET}/{lesson_id}", headers=customer).json()
    assert one["places"] == [
        {"value": "leads", "label": "Lidlar"},
        {"value": "crm", "label": "CRM"},
    ], "catalogue order, each once"
    assert (
        client.get(f"{CABINET}/{plain.json()['id']}", headers=customer).json()["places"]
        == []
    )

    listed = client.get(CABINET, headers=customer).json()
    assert listed["total"] == 2, "the section shows every lesson"
    assert {"value": "crm", "label": "CRM"} in listed["places"]
    crm = client.get(CABINET, headers=customer, params={"place": "crm"}).json()
    assert [row["id"] for row in crm["rows"]] == [lesson_id]
    assert (
        client.get(CABINET, headers=customer, params={"place": "billing"}).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.get(CABINET, headers=customer, params={"place": "kino"}).status_code
        == 422
    )
    assert (
        client.get(OFFICE, headers=office, params={"place": "leads"}).json()["total"]
        == 1
    )

    kept = client.put(
        f"{OFFICE}/{lesson_id}",
        headers=office,
        data=_form(title="Yangi nom", video_url="https://youtu.be/dQw4w9WgXcQ"),
    )
    assert kept.status_code == 200, kept.text
    assert [
        p["value"]
        for p in client.get(f"{OFFICE}/{lesson_id}", headers=office).json()["places"]
    ] == ["leads", "crm"], "an edit without the field keeps the places"

    moved = client.put(
        f"{OFFICE}/{lesson_id}",
        headers=office,
        data=_form(video_url="https://youtu.be/dQw4w9WgXcQ") | {"places": ["billing"]},
    )
    assert moved.status_code == 200, moved.text
    assert (
        client.get(CABINET, headers=customer, params={"place": "crm"}).json()["total"]
        == 0
    )

    cleared = client.put(
        f"{OFFICE}/{lesson_id}",
        headers=office,
        data=_form(video_url="https://youtu.be/dQw4w9WgXcQ") | {"places": ""},
    )
    assert cleared.status_code == 200, cleared.text
    assert client.get(f"{OFFICE}/{lesson_id}", headers=office).json()["places"] == []

    client.patch(f"{OFFICE}/{lesson_id}/status", headers=office, json={"status": False})
    client.put(
        f"{OFFICE}/{lesson_id}",
        headers=office,
        data=_form(video_url="https://youtu.be/dQw4w9WgXcQ", status="false")
        | {"places": ["crm"]},
    )
    assert (
        client.get(CABINET, headers=customer, params={"place": "crm"}).json()["total"]
        == 0
    ), "a hidden lesson shows on no screen"


def test_a_lesson_comes_in_the_readers_language_or_its_only_one(
    client: TestClient, db: Session, media_root: Path
) -> None:
    """Uzbek is the plain fields, Russian and English end in _ru/_en; a reader
    gets their own language, else the first written of uz, ru, en."""
    _, office = _staff(db, Role.SUPPORT, email="lang@office.test")
    customer = sign_up(client)
    upload_id = _upload(client, office, MP4)

    three = client.post(
        OFFICE,
        headers=office,
        data=_form(video_url="https://youtu.be/dQw4w9WgXcQ")
        | {
            "title_ru": "Подключение пикселя",
            "description_ru": "Как подключить пиксель",
            "video_upload_id_ru": upload_id,
            "video_size_ru": str(len(MP4)),
            "video_name_ru": "urok.mp4",
            "title_en": "Connecting the pixel",
            "video_url_en": "https://vimeo.com/7",
        },
        files={"image_ru": ("ru.png", PNG, "image/png")},
    )
    assert three.status_code == 200, three.text
    lesson = three.json()["id"]
    only_ru = client.post(
        OFFICE,
        headers=office,
        data=_form(title="", description="", status="true")
        | {"title_ru": "Только по-русски", "video_url_ru": "https://vimeo.com/8"},
    )
    assert only_ru.status_code == 200, only_ru.text

    def seen(lang: str | None, pk: str = lesson) -> dict[str, Any]:
        params = {"lang": lang} if lang else {}
        answer = client.get(f"{CABINET}/{pk}", headers=customer, params=params)
        assert answer.status_code == 200, answer.text
        return answer.json()

    uz = seen("uz")
    assert (uz["language"], uz["title"]) == ("uz", "Pikselni ulash")
    assert uz["languages"] == ["uz", "ru", "en"]
    assert uz["video"]["kind"] == "youtube"
    assert uz["image_url"] and "lang=ru" in uz["image_url"], "another language's cover"
    ru = seen("ru")
    assert (ru["language"], ru["title"], ru["description"]) == (
        "ru",
        "Подключение пикселя",
        "Как подключить пиксель",
    )
    assert ru["video"]["kind"] == "file"
    played = client.get(ru["video"]["stream_url"])
    assert played.status_code == 206 and played.content == MP4[:STREAM_PIECE_BYTES]
    assert client.get(ru["image_url"]).content == PNG
    en = seen("en")
    assert (en["title"], en["video"]["url"]) == (
        "Connecting the pixel",
        "https://vimeo.com/7",
    )
    client.put("/api/v1/account/language", json={"language": "en"}, headers=customer)
    assert seen(None)["language"] == "en", "no lang: the account's language"

    for lang in ("uz", "ru", "en"):
        one = seen(lang, only_ru.json()["id"])
        assert (one["language"], one["title"]) == ("ru", "Только по-русски")

    listed = client.get(CABINET, headers=customer, params={"lang": "ru"}).json()
    assert {row["title"] for row in listed["rows"]} == {
        "Подключение пикселя",
        "Только по-русски",
    }
    assert [c["value"] for c in listed["languages"]] == ["uz", "ru", "en"]
    found = client.get(CABINET, headers=customer, params={"q": "пиксел", "lang": "uz"})
    assert [row["title"] for row in found.json()["rows"]] == ["Pikselni ulash"]

    versions = client.get(f"{OFFICE}/{lesson}", headers=office).json()["versions"]
    assert versions["ru"]["has_video_file"] and versions["ru"]["has_image"]
    assert versions["uz"]["image_url"] is None and versions["en"]["video_url"]

    half = client.put(
        f"{OFFICE}/{lesson}",
        headers=office,
        data=_form(video_url="https://youtu.be/dQw4w9WgXcQ")
        | {"title_ru": "Подключение пикселя", "description_en": "Only words"},
    )
    assert half.status_code == 422
    assert set(half.json()["problems"]) == {"title_en", "video_en"}, half.text

    dropped = client.put(
        f"{OFFICE}/{lesson}",
        headers=office,
        data=_form(video_url="https://youtu.be/dQw4w9WgXcQ")
        | {"remove_video_ru": "true", "remove_image_ru": "true"},
    )
    assert dropped.status_code == 200, dropped.text
    assert seen("ru")["language"] == "uz", "a language sent empty is dropped"
    assert seen("ru")["languages"] == ["uz"]
    assert not list((media_root / "tutorials").rglob("*.mp4"))
    assert not list((media_root / "tutorials" / "images").rglob("*.png"))

    nothing = client.post(OFFICE, headers=office, data=_form(title="", description=""))
    assert set(nothing.json()["problems"]) == {"title", "video"}


def test_the_assistant_offers_a_lesson_in_the_readers_language(
    db: Session,
) -> None:
    from app.modules.assistant.selectors.help import help_found

    db.add(
        Tutorial(
            title="Pikselni ulash",
            video_url="https://vimeo.com/1",
            title_ru="Подключение пикселя",
            description_ru="Откройте Events Manager",
            video_url_ru="https://vimeo.com/2",
            is_active=True,
        )
    )
    db.add(
        Tutorial(
            title="Reklama kabinetini ochish",
            video_url="https://vimeo.com/3",
            is_active=True,
        )
    )
    db.commit()

    ru = help_found(db, query="пиксель подключить", language="ru")
    assert [(f.problem, f.steps) for f in ru if f.lesson_id] == [
        ("Подключение пикселя", ("Откройте Events Manager",))
    ]
    uz = help_found(db, query="piksel ulash", language="uz")
    assert [f.problem for f in uz if f.lesson_id] == ["Pikselni ulash"]
    en = help_found(db, query="kabinetini ochish", language="en")
    assert [f.problem for f in en if f.lesson_id] == ["Reklama kabinetini ochish"]
    across = help_found(db, query="piksel", language="ru")
    assert [f.problem for f in across if f.lesson_id] == ["Подключение пикселя"]
