"""An advert named on a CRM card carries its picture and whether it is a video."""

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import AdCreative
from app.modules.ads.selectors import ad_labels
from tests.pg.conftest import sign_up
from tests.pg.test_ads_editing import _running
from tests.pg.test_cabinet_flows import _cabinet


def _owner(client: TestClient, db: Session) -> User:
    sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    assert owner is not None
    account, _page = _cabinet(db, owner)
    _running(db, owner, account)
    return owner


def test_the_picture_and_format_come_only_when_asked_for(
    client: TestClient, db: Session
) -> None:
    owner = _owner(client, db)
    db.execute(
        update(AdCreative)
        .where(AdCreative.external_id == "cr_1")
        .values(thumbnail_url="https://cdn.example/t.jpg")
    )
    db.commit()

    plain = ad_labels(db, owner=owner, external_ids=["a_1"])["a_1"]
    drawn = ad_labels(db, owner=owner, external_ids=["a_1"], with_media=True)["a_1"]

    assert plain.thumb_url == "" and plain.format == ""
    assert drawn.thumb_url == "https://cdn.example/t.jpg"
    assert drawn.format == "image"
    assert drawn.name == plain.name == "Reklama a_1"


def test_a_boosted_video_post_is_named_a_video(client: TestClient, db: Session) -> None:
    owner = _owner(client, db)
    db.execute(
        update(AdCreative)
        .where(AdCreative.external_id == "cr_1")
        .values(kind="post", is_video=True, thumbnail_url="not-a-url")
    )
    db.commit()

    label = ad_labels(db, owner=owner, external_ids=["a_1"], with_media=True)["a_1"]

    assert label.format == "video"
    assert label.thumb_url == ""


def test_an_advert_whose_creative_is_not_mirrored_has_no_picture(
    client: TestClient, db: Session
) -> None:
    owner = _owner(client, db)
    db.execute(update(AdCreative).values(external_id="cr_other"))
    db.commit()

    label = ad_labels(db, owner=owner, external_ids=["a_1"], with_media=True)["a_1"]

    assert label.thumb_url == "" and label.format == ""
