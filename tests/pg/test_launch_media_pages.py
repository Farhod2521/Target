"""The pictures step a page at a time: an account with thousands of posts
must not arrive in one answer, and a tick pages down must still count."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.constants import MEDIA_PAGE_SIZE, MediaKind
from app.modules.ads.models import CampaignLaunch, MediaAsset
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.variants import launch_variants
from app.modules.ads.services import playback
from tests.pg.test_launch_drafts import _opened, quick_reading  # noqa: F401


def _at_media(
    client: TestClient, db: Session
) -> tuple[dict[str, str], str, CampaignLaunch]:
    auth, draft_id = _opened(client, db)
    path = f"/api/v1/launch/drafts/{draft_id}"
    floor = client.get(path, headers=auth).json()["minBudget"]
    went = client.patch(
        path,
        json={
            "goal": "click",
            "linkUrl": "bahor.example",
            "dailyBudget": floor | {"minor": 500},
            "step": "media",
        },
        headers=auth,
    )
    assert went.status_code == 200, went.text
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    return auth, path, launch


def _library(db: Session, launch: CampaignLaunch, count: int) -> list[MediaAsset]:
    """``count`` files, newest first by index; every tenth Meta gave no date."""
    now = utcnow()
    rows = [
        MediaAsset(
            owner_id=launch.owner_id,
            ad_account_id=launch.ad_account_id,
            provider=launch.provider,
            kind=MediaKind.IMAGE,
            external_id=f"hash_{index}",
            name=f"rasm_{index}.jpg",
            width=1080,
            height=1080,
            created_at_provider=None
            if index % 10 == 9
            else now - timedelta(hours=index),
        )
        for index in range(count)
    ]
    db.add_all(rows)
    db.commit()
    return rows


def _instagram(db: Session, launch: CampaignLaunch, count: int) -> list[MediaAsset]:
    """The page's Instagram, every third post one Meta will not advertise."""
    page = launch_page(db, launch=launch)
    assert page is not None
    page.instagram_user_id, page.instagram_username = "ig_1", "bahor"
    now = utcnow()
    rows = [
        MediaAsset(
            owner_id=launch.owner_id,
            page_id=page.id,
            instagram_user_id="ig_1",
            provider=launch.provider,
            kind=MediaKind.IG_VIDEO if index % 3 == 0 else MediaKind.IG_IMAGE,
            external_id=f"ig_{index}",
            name=f"post {index}",
            is_eligible=index % 3 != 0,
            ineligible_reason="Remove or choose different audio."
            if index % 3 == 0
            else "",
            created_at_provider=now - timedelta(minutes=index),
        )
        for index in range(count)
    ]
    db.add_all(rows)
    db.commit()
    return rows


def _walk(
    client: TestClient, path: str, auth: dict[str, str], **query: str
) -> list[str]:
    seen: list[str] = []
    after = ""
    for _ in range(20):
        got = client.get(
            f"{path}/media/items", params={**query, "after": after}, headers=auth
        )
        assert got.status_code == 200, got.text
        body = got.json()
        seen += [item["id"] for item in body["items"]]
        after = body["after"]
        if not after:
            return seen
    raise AssertionError("the pages never ended")


def test_the_library_arrives_a_page_at_a_time(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, path, launch = _at_media(client, db)
    rows = _library(db, launch, 130)

    first = client.get(f"{path}/media", headers=auth).json()
    assert len(first["library"]) == MEDIA_PAGE_SIZE
    assert first["libraryTotal"] == 130 and first["libraryAfter"]

    every = _walk(client, path, auth, source="lib")
    dated = sorted(
        (row for row in rows if row.created_at_provider is not None),
        key=lambda row: row.created_at_provider,  # type: ignore[arg-type, return-value]
        reverse=True,
    )
    undated = [row for row in rows if row.created_at_provider is None]
    assert every[: len(dated)] == [str(row.id) for row in dated]
    assert set(every[len(dated) :]) == {str(row.id) for row in undated}
    assert len(every) == len(set(every)) == 130
    assert every[:MEDIA_PAGE_SIZE] == [tile["id"] for tile in first["library"]]


def test_a_cursor_that_does_not_read_is_the_first_page(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, path, launch = _at_media(client, db)
    _library(db, launch, 5)
    got = client.get(
        f"{path}/media/items",
        params={"source": "lib", "after": "not-a-cursor!"},
        headers=auth,
    )
    assert got.status_code == 200, got.text
    assert len(got.json()["items"]) == 5 and got.json()["after"] == ""


def test_instagram_filters_on_what_meta_refuses(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, path, launch = _at_media(client, db)
    rows = _instagram(db, launch, 100)
    refused = {str(row.id) for row in rows if row.is_eligible is False}

    first = client.get(f"{path}/media", headers=auth).json()
    assert first["instagram"] is not None
    assert len(first["posts"]) == MEDIA_PAGE_SIZE and first["postsTotal"] == 100

    assert set(_walk(client, path, auth, source="ig", show="blocked")) == refused
    usable = _walk(client, path, auth, source="ig", show="usable")
    assert len(usable) == 100 - len(refused) and not refused & set(usable)
    assert len(_walk(client, path, auth, source="ig")) == 100


def test_a_tick_pages_down_is_drawn_and_sent(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, path, launch = _at_media(client, db)
    rows = _library(db, launch, 130)
    deep = rows[120]
    first = client.get(f"{path}/media", headers=auth).json()
    assert deep.id not in {tile["id"] for tile in first["library"]}

    ticked = client.patch(
        path, json={"media": [str(deep.id)], "offer": "Yangi osh"}, headers=auth
    )
    assert ticked.status_code == 200, ticked.text
    shown = client.get(f"{path}/media", headers=auth).json()
    assert [tile["id"] for tile in shown["chosen"]] == [str(deep.id)]

    tile = client.get(f"{path}/media/tiles/{deep.id}", headers=auth)
    assert tile.status_code == 200 and tile.json()["id"] == str(deep.id)

    built = client.post(f"{path}/build", headers=auth)
    assert built.status_code == 200, built.text
    assert [
        variant.media_asset_id for variant in launch_variants(db, launch=launch)
    ] == [deep.id]


def test_a_tick_on_a_file_since_deleted_is_not_sent(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, path, launch = _at_media(client, db)
    kept, gone = _library(db, launch, 2)
    ticked = client.patch(
        path,
        json={"media": [str(kept.id), str(gone.id)], "offer": "Yangi osh"},
        headers=auth,
    )
    assert ticked.status_code == 200, ticked.text
    db.delete(gone)
    db.commit()

    built = client.post(f"{path}/build", headers=auth)
    assert built.status_code == 200, built.text
    assert [
        variant.media_asset_id for variant in launch_variants(db, launch=launch)
    ] == [kept.id]


def test_someone_elses_tile_is_not_found(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, path, launch = _at_media(client, db)
    stranger = MediaAsset(
        owner_id=launch.owner_id,
        ad_account_id=None,
        provider=launch.provider,
        kind=MediaKind.IMAGE,
        external_id="elsewhere",
    )
    db.add(stranger)
    db.commit()
    got = client.get(f"{path}/media/tiles/{stranger.id}", headers=auth)
    assert got.status_code == 404


def test_a_tile_says_why_meta_refuses_it_and_what_it_is(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, path, launch = _at_media(client, db)
    page = launch_page(db, launch=launch)
    assert page is not None
    page.instagram_user_id, page.instagram_username = "ig_1", "bahor"
    now = utcnow()
    said = {
        "audio": "Remove or choose different audio.",
        "tappable": "Reels containing tappable elements can't be used for ads. "
        "Choose a different post to create an ad.",
        "long": "Reels must be 15 minutes or shorter to be boosted as ads.",
        "odd": "Something Meta has not said before.",
    }
    for index, (name, reason) in enumerate(said.items()):
        db.add(
            MediaAsset(
                owner_id=launch.owner_id,
                page_id=page.id,
                instagram_user_id="ig_1",
                provider=launch.provider,
                kind=MediaKind.IG_VIDEO,
                external_id=name,
                name=name,
                product="REELS",
                is_eligible=False,
                ineligible_reason=reason,
                created_at_provider=now - timedelta(minutes=index),
            )
        )
    db.add(
        MediaAsset(
            owner_id=launch.owner_id,
            page_id=page.id,
            instagram_user_id="ig_1",
            provider=launch.provider,
            kind=MediaKind.IG_IMAGE,
            external_id="album",
            name="album",
            product="FEED",
            is_carousel=True,
            is_eligible=True,
            created_at_provider=now - timedelta(days=1),
        )
    )
    db.add(
        MediaAsset(
            owner_id=launch.owner_id,
            ad_account_id=launch.ad_account_id,
            provider=launch.provider,
            kind=MediaKind.VIDEO,
            external_id="v1",
            name="kino.mp4",
            width=320,
            height=320,
            duration_seconds=31.4,
        )
    )
    db.commit()

    shown = client.get(f"{path}/media", headers=auth).json()
    posts = {tile["caption"]: tile for tile in shown["posts"]}
    assert {name: posts[name]["blockedReason"] for name in said} == {
        "audio": "music",
        "tappable": "tappable",
        "long": "too_long",
        "odd": "other",
    }
    assert all(posts[name]["blocked"] and posts[name]["reel"] for name in said)
    album = posts["album"]
    assert album["carousel"] and not album.get("reel") and not album.get("blocked")
    assert album["date"].startswith((now - timedelta(days=1)).date().isoformat())
    video = shown["library"][0]
    assert video["video"] == "0:31" and video["small"]


class _Meta:
    """Stands in for Meta's video reads and counts them."""

    def __init__(self, answer: str = "https://video.example/fresh.mp4") -> None:
        self.answer = answer
        self.asked: list[str] = []
        self.fails = False

    def video_source(self, *, video_id: str, token: str) -> str:
        return self._read(f"video:{video_id}")

    def instagram_source(self, *, media_id: str, token: str) -> str:
        return self._read(f"ig:{media_id}")

    def _read(self, what: str) -> str:
        from adskit.errors import TemporaryFailure

        self.asked.append(what)
        if self.fails:
            raise TemporaryFailure("Meta is down")
        return self.answer


def _meta(monkeypatch: pytest.MonkeyPatch, meta: _Meta) -> None:
    monkeypatch.setattr(playback, "MetaAssets", lambda: meta)
    monkeypatch.setattr(playback, "token_for", lambda **_: "user-token")
    monkeypatch.setattr(playback, "profile_token", lambda _asset: "page-token")


def _signed(hours: float) -> str:
    ends = int((utcnow() + timedelta(hours=hours)).timestamp())
    return f"https://video.xx.fbcdn.net/v/clip.mp4?_nc_cat=1&oe={ends:X}&_nc_sid=2"


def _video(
    db: Session, launch: CampaignLaunch, *, stored: str, name: str
) -> MediaAsset:
    row = MediaAsset(
        owner_id=launch.owner_id,
        ad_account_id=launch.ad_account_id,
        provider=launch.provider,
        kind=MediaKind.VIDEO,
        external_id=name,
        name=f"{name}.mp4",
        permalink_url=stored,
    )
    db.add(row)
    db.commit()
    return row


def test_a_library_video_plays_from_its_stored_address_while_it_lasts(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, path, launch = _at_media(client, db)
    meta = _Meta()
    _meta(monkeypatch, meta)
    stored = _signed(hours=48)
    video = _video(db, launch, stored=stored, name="v_lasts")

    got = client.get(f"{path}/media/tiles/{video.id}/play", headers=auth)

    assert got.status_code == 200, got.text
    assert got.json() == {"url": stored} and meta.asked == []


def test_an_expiring_address_is_asked_for_again_and_kept_a_while(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, path, launch = _at_media(client, db)
    meta = _Meta()
    _meta(monkeypatch, meta)
    video = _video(db, launch, stored=_signed(hours=0.5), name="v_old")

    first = client.get(f"{path}/media/tiles/{video.id}/play", headers=auth)
    again = client.get(f"{path}/media/tiles/{video.id}/play", headers=auth)

    assert first.json() == again.json() == {"url": meta.answer}
    assert meta.asked == ["video:v_old"]


def test_an_instagram_reel_is_always_asked_for(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, path, launch = _at_media(client, db)
    meta = _Meta()
    _meta(monkeypatch, meta)
    reel = next(
        row for row in _instagram(db, launch, 3) if row.kind == MediaKind.IG_VIDEO
    )

    got = client.get(f"{path}/media/tiles/{reel.id}/play", headers=auth)

    assert got.status_code == 200, got.text
    assert meta.asked == [f"ig:{reel.external_id}"]


def test_a_video_meta_withholds_or_cannot_read_says_so(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, path, launch = _at_media(client, db)
    withheld = _Meta(answer="")
    _meta(monkeypatch, withheld)
    quiet = _video(db, launch, stored="", name="v_quiet")
    got = client.get(f"{path}/media/tiles/{quiet.id}/play", headers=auth)
    assert got.status_code == 404 and "ko'rsatmadi" in got.text

    down = _Meta()
    down.fails = True
    _meta(monkeypatch, down)
    broken = _video(db, launch, stored="", name="v_down")
    got = client.get(f"{path}/media/tiles/{broken.id}/play", headers=auth)
    assert got.status_code == 503 and "qayta urining" in got.text

    picture = _library(db, launch, 1)[0]
    got = client.get(f"{path}/media/tiles/{picture.id}/play", headers=auth)
    assert got.status_code == 400 and "video emas" in got.text


def test_a_library_sync_no_longer_reads_the_page_s_facebook_posts(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    from metaads import creatives

    from app.modules.ads.services import media

    _auth, _path, launch = _at_media(client, db)
    visited: list[str] = []

    def refused(**_: object) -> list[object]:
        raise AssertionError("the page's Facebook posts were read")

    def instagram(_db: Session, *, page: object, **_: object) -> int:
        visited.append(str(getattr(page, "external_id", "")))
        return 0

    monkeypatch.setattr(creatives, "list_page_posts", refused)
    monkeypatch.setattr(media, "decrypt", lambda _stored: "page-token")
    monkeypatch.setattr(media, "_instagram_library", instagram)

    assert media.sync_owner_media(db, owner_id=launch.owner_id) == "0"
    assert visited == ["page_1"]
    assert not db.scalars(
        select(MediaAsset).where(MediaAsset.kind == MediaKind.POST)
    ).all()
