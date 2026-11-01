"""Fikrlar: who answers a piece, what it pays, its file, and the site's cards."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import storage
from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.billing.constants import SubscriptionStatus
from app.modules.billing.models import Plan, Subscription
from app.modules.public.models import Testimonial
from app.modules.referrals.constants import FeedbackKind, FeedbackStatus
from app.modules.referrals.models import Feedback
from app.modules.referrals.selectors import available_minor
from tests.pg.test_office_actions import _shop, _staff

URL = "/api/v1/office"
WORDS = "Zo'r xizmat. " * 12


@pytest.fixture(autouse=True)
def media(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    yield tmp_path


def _piece(db: Session, owner: User, **fields: object) -> Feedback:
    piece = Feedback(
        owner_id=owner.id,
        kind=fields.pop("kind", FeedbackKind.TEXT),
        status=fields.pop("status", FeedbackStatus.PENDING),
        text=fields.pop("text", WORDS),
        consented_at=utcnow(),
        **fields,
    )
    db.add(piece)
    db.commit()
    return piece


def _recording(root: Path, name: str = "feedback/a.mp4", body: bytes = b"0123456789") -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return name


def _kinds(db: Session, owner: User) -> list[str]:
    return list(
        db.scalars(select(StaffAction.kind).where(StaffAction.owner_id == owner.id))
    )


@pytest.mark.parametrize("role", [Role.SUPPORT, Role.FINANCE, Role.SALES])
def test_only_the_owner_answers_a_piece(
    client: TestClient, db: Session, role: Role
) -> None:
    _, headers = _staff(db, role, email="member@office.test")
    shop, _ = _shop(db)
    piece = _piece(db, shop)

    assert client.get(f"{URL}/feedback", headers=headers).status_code == 404
    assert client.get(f"{URL}/feedback/publishable", headers=headers).status_code == 404
    for answer in ("approve", "publish"):
        refused = client.post(f"{URL}/feedback/{piece.id}/{answer}", headers=headers)
        assert refused.status_code == 404
    db.expire_all()
    assert db.get(Feedback, piece.id).status == FeedbackStatus.PENDING


def test_the_queue_says_what_approving_would_pay(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, _ = _shop(db)
    piece = _piece(db, shop)

    body = client.get(f"{URL}/feedback", headers=headers).json()

    row = body["rows"][0]
    assert row["id"] == str(piece.id)
    assert row["plan_name"] == "Pro"
    assert row["reward_percent"] > 0
    assert row["reward_minor"] == 49000000 * row["reward_percent"] // 100
    assert row["file_url"] == ""


def test_a_customer_on_no_paid_plan_earns_nothing(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, plan = _shop(db, subscribed=False)
    piece = _piece(db, shop)
    row = client.get(f"{URL}/feedback", headers=headers).json()["rows"][0]
    assert row["reward_minor"] is None and row["plan_name"] == "Tarifsiz"

    trial = Plan(code="sinov", name="Sinov", price=0, currency="UZS", period_days=7,
                 max_adsets=1, llm_cost_limit_minor=0)  # fmt: skip
    db.add(trial)
    db.flush()
    now = utcnow()
    db.add(Subscription(owner_id=shop.id, plan_id=trial.id,
                        status=SubscriptionStatus.TRIAL, started_at=now,
                        expires_at=now + timedelta(days=3)))  # fmt: skip
    db.commit()
    row = client.get(f"{URL}/feedback", headers=headers).json()["rows"][0]
    assert row["reward_minor"] is None and row["plan_name"] == "Sinov"

    refused = client.post(f"{URL}/feedback/{piece.id}/approve", headers=headers)
    assert refused.status_code == 400, refused.text
    db.expire_all()
    assert db.get(Feedback, piece.id).status == FeedbackStatus.PENDING
    assert plan.id is not None


def test_approving_pays_the_balance_once_and_is_journalled(
    client: TestClient, db: Session
) -> None:
    member, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, _ = _shop(db)
    piece = _piece(db, shop)

    done = client.post(f"{URL}/feedback/{piece.id}/approve", headers=headers)
    assert done.status_code == 200, done.text
    db.expire_all()
    row = db.get(Feedback, piece.id)
    assert row.status == FeedbackStatus.APPROVED and row.decided_by_id == member.id
    assert row.amount_minor > 0
    assert available_minor(db, owner=shop, currency=row.currency) == row.amount_minor
    assert _kinds(db, shop) == [ActionKind.FEEDBACK_APPROVED]

    again = client.post(f"{URL}/feedback/{piece.id}/approve", headers=headers)
    assert again.status_code == 400
    assert available_minor(db, owner=shop, currency=row.currency) == row.amount_minor

    recent = client.get(f"{URL}/feedback", headers=headers).json()["recent"]
    assert recent[0]["approved"] is True
    assert recent[0]["amount_minor"] == row.amount_minor


def test_turning_down_needs_a_reason_and_pays_nothing(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, _ = _shop(db)
    piece = _piece(db, shop)

    for blank in ("", "   "):
        empty = client.post(
            f"{URL}/feedback/{piece.id}/reject", headers=headers, json={"reason": blank}
        )
        assert empty.status_code in {400, 422}

    done = client.post(
        f"{URL}/feedback/{piece.id}/reject",
        headers=headers,
        json={"reason": "Juda qisqa"},
    )
    assert done.status_code == 200, done.text
    db.expire_all()
    assert db.get(Feedback, piece.id).reason == "Juda qisqa"
    assert available_minor(db, owner=shop, currency="UZS") == 0
    assert _kinds(db, shop) == [ActionKind.FEEDBACK_REJECTED]
    recent = client.get(f"{URL}/feedback", headers=headers).json()["recent"]
    assert recent[0]["approved"] is False and recent[0]["reason"] == "Juda qisqa"


def test_an_unknown_piece_is_a_missing_page(client: TestClient, db: Session) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    missing = "00000000-0000-0000-0000-000000000000"
    for answer in ("approve", "publish"):
        assert (
            client.post(f"{URL}/feedback/{missing}/{answer}", headers=headers).status_code
            == 404
        )
    assert client.get(f"{URL}/feedback/{missing}/file", headers=headers).status_code == 404


def test_the_recording_plays_by_token_in_pieces_and_is_journalled(
    client: TestClient, db: Session, media: Path
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    token = headers["Authorization"].removeprefix("Bearer ")
    shop, _ = _shop(db)
    piece = _piece(db, shop, kind=FeedbackKind.VIDEO, text="", file=_recording(media))

    whole = client.get(f"{URL}/feedback/{piece.id}/file?token={token}")
    assert whole.status_code == 200, whole.text
    assert whole.headers["content-type"].startswith("video/mp4")
    assert "inline" in whole.headers.get("content-disposition", "inline")

    part = client.get(
        f"{URL}/feedback/{piece.id}/file?token={token}", headers={"Range": "bytes=2-5"}
    )
    assert part.status_code == 206 and part.content == b"2345"
    assert _kinds(db, shop) == [ActionKind.FEEDBACK_FILE], "one opening, many pieces"


def test_a_recording_gone_from_disk_is_a_missing_page(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, _ = _shop(db)
    piece = _piece(db, shop, kind=FeedbackKind.VIDEO, text="", file="feedback/gone.mp4")
    assert client.get(f"{URL}/feedback/{piece.id}/file", headers=headers).status_code == 404


def test_a_role_without_the_door_hears_nothing_even_with_a_token(
    client: TestClient, db: Session, media: Path
) -> None:
    _, headers = _staff(db, Role.SUPPORT, email="support@office.test")
    token = headers["Authorization"].removeprefix("Bearer ")
    shop, _ = _shop(db)
    piece = _piece(db, shop, kind=FeedbackKind.VIDEO, text="", file=_recording(media))
    assert client.get(f"{URL}/feedback/{piece.id}/file?token={token}").status_code == 404
    assert _kinds(db, shop) == []


def test_publishing_copies_the_recording_to_a_card_once(
    client: TestClient, db: Session, media: Path
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, _ = _shop(db)
    piece = _piece(
        db,
        shop,
        kind=FeedbackKind.VIDEO,
        text="",
        file=_recording(media),
        status=FeedbackStatus.APPROVED,
        decided_at=utcnow(),
    )
    offered = client.get(f"{URL}/feedback/publishable", headers=headers).json()["rows"]
    assert [row["id"] for row in offered] == [str(piece.id)]

    done = client.post(f"{URL}/feedback/{piece.id}/publish", headers=headers)

    assert done.status_code == 200, done.text
    card = db.scalar(select(Testimonial))
    assert card.source_id == piece.id and card.video
    assert (media / card.video).read_bytes() == b"0123456789"
    assert _kinds(db, shop) == [ActionKind.FEEDBACK_PUBLISHED]
    assert client.get(f"{URL}/feedback/publishable", headers=headers).json()["rows"] == []
    again = client.post(f"{URL}/feedback/{piece.id}/publish", headers=headers)
    assert again.status_code == 400

    cards = client.get(f"{URL}/testimonials", headers=headers).json()
    assert cards[0]["from_customer"] is True and cards[0]["name"] == "Shop"
    assert cards[0]["size_bytes"] == 10


def test_a_waiting_piece_does_not_go_on_the_site(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, _ = _shop(db)
    piece = _piece(db, shop)
    refused = client.post(f"{URL}/feedback/{piece.id}/publish", headers=headers)
    assert refused.status_code == 400
    assert db.scalar(select(Testimonial)) is None


def test_publishing_a_recording_gone_from_disk_says_so(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, _ = _shop(db)
    piece = _piece(
        db, shop, kind=FeedbackKind.VIDEO, text="", file="feedback/gone.mp4",
        status=FeedbackStatus.APPROVED,
    )  # fmt: skip
    refused = client.post(f"{URL}/feedback/{piece.id}/publish", headers=headers)
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "Fikr fayli topilmadi."


def test_support_keeps_the_carousel_and_a_seller_does_not(
    client: TestClient, db: Session
) -> None:
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _, seller = _staff(db, Role.SALES, email="seller@office.test")
    assert client.get(f"{URL}/testimonials", headers=support).json() == []
    assert client.get(f"{URL}/testimonials", headers=seller).status_code == 404


def _add(client: TestClient, headers: dict[str, str], **form: object) -> object:
    files = form.pop("files", None)
    return client.post(
        f"{URL}/testimonials", headers=headers, data=form, files=files
    )


def test_a_text_card_is_added_changed_and_removed(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.SUPPORT, email="support@office.test")

    added = _add(client, headers, media="text", text=" Zo'r ", order=3, visible="1")
    assert added.status_code == 200, added.text
    card = client.get(f"{URL}/testimonials", headers=headers).json()[0]
    assert card["text"] == "Zo'r" and card["sort_order"] == 3 and card["is_active"]

    saved = client.patch(
        f"{URL}/testimonials/{card['id']}",
        headers=headers,
        json={"is_active": False, "sort_order": 0},
    )
    assert saved.status_code == 200, saved.text
    shown = client.get(f"{URL}/testimonials", headers=headers).json()[0]
    assert shown["is_active"] is False and shown["sort_order"] == 0

    gone = client.delete(f"{URL}/testimonials/{card['id']}", headers=headers)
    assert gone.status_code == 200, gone.text
    assert client.get(f"{URL}/testimonials", headers=headers).json() == []


def test_a_picture_card_serves_its_file_and_deleting_removes_it(
    client: TestClient, db: Session, media: Path
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    added = _add(
        client, headers, media="image", order=0, visible="1",
        files={"file": ("a.png", b"png-bytes", "image/png")},
    )  # fmt: skip
    assert added.status_code == 200, added.text
    card = client.get(f"{URL}/testimonials", headers=headers).json()[0]
    assert card["image"] and card["size_bytes"] == 9
    row = db.scalar(select(Testimonial))
    assert storage.media_path(row.image).is_file()

    client.delete(f"{URL}/testimonials/{card['id']}", headers=headers)
    assert not storage.media_path(row.image).exists()


def test_a_video_keeps_its_cover_as_the_cards_picture(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    added = _add(
        client, headers, media="video", order=0, visible="1",
        files={
            "file": ("a.mp4", b"v", "video/mp4"),
            "cover": ("c.png", b"c", "image/png"),
        },
    )  # fmt: skip
    assert added.status_code == 200, added.text
    card = client.get(f"{URL}/testimonials", headers=headers).json()[0]
    assert card["kind"] == "video" and card["video"] and card["image"]


@pytest.mark.parametrize(
    ("form", "field"),
    [
        ({"media": "text", "text": "   "}, "text"),
        ({"media": "image"}, "file"),
        ({"media": "video"}, "file"),
        ({"media": "audio"}, "file"),
    ],
)
def test_a_card_with_nothing_to_show_is_refused(
    client: TestClient, db: Session, form: dict[str, str], field: str
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    refused = _add(client, headers, **form)
    assert refused.status_code == 422, refused.text
    assert field in refused.json()["problems"]
    assert db.scalar(select(Testimonial)) is None


def test_a_file_of_another_format_is_refused(client: TestClient, db: Session) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    refused = _add(
        client, headers, media="image",
        files={"file": ("a.exe", b"x", "application/octet-stream")},
    )  # fmt: skip
    assert refused.status_code == 400, refused.text
    assert db.scalar(select(Testimonial)) is None


def test_an_order_outside_the_range_and_an_unknown_card_are_refused(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    assert _add(client, headers, media="text", text="x", order=-1).status_code == 422
    missing = "00000000-0000-0000-0000-000000000000"
    patched = client.patch(
        f"{URL}/testimonials/{missing}",
        headers=headers,
        json={"is_active": True, "sort_order": 40000},
    )
    assert patched.status_code == 422
    assert client.delete(f"{URL}/testimonials/{missing}", headers=headers).status_code in {400, 404}
