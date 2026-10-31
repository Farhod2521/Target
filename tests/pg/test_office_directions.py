"""The office's business directions: the superuser's, and always on a real preset."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.businesses.models import Business, BusinessCategory
from tests.pg.test_launch_api import _ready
from tests.pg.test_office_actions import _staff

URL = "/api/v1/office/directions"
DRAFTS = "/api/v1/launch/drafts"


def _new(**fields: object) -> dict[str, object]:
    return {
        "key": " Moliya ",
        "label_uz": " Moliya ",
        "preset_key": "services",
    } | fields


def _profile(direction: str) -> dict[str, object]:
    return {
        "name": "Naqd",
        "category": direction,
        "country_code": "UZ",
        "timezone": "Asia/Tashkent",
    }


def _open(client: TestClient, auth: dict[str, str]) -> tuple[int, str | None]:
    opened = client.post(
        DRAFTS, json={"flow": "campaigns", "resume": None}, headers=auth
    )
    return opened.status_code, opened.json().get("code")


def test_only_the_superuser_opens_the_door(client: TestClient, db: Session) -> None:
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    _, chief = _staff(db, email="chief@office.test", superuser=True)

    assert client.get(URL, headers=owner).status_code == 404
    assert client.post(URL, headers=owner, json=_new()).status_code == 404
    assert client.get(URL).status_code == 401

    made = client.post(URL, headers=chief, json=_new())
    assert made.status_code == 200, made.text
    row = db.scalar(select(BusinessCategory).where(BusinessCategory.key == "moliya"))
    assert row is not None and row.label_uz == "Moliya"
    assert client.delete(f"{URL}/{row.id}", headers=owner).status_code == 404

    listed = client.get(URL, headers=chief).json()
    assert [item["key"] for item in listed["rows"]] == ["moliya"]
    assert listed["rows"][0]["preset_label"] == "Xizmatlar"
    assert listed["rows"][0]["businesses"] == 0
    assert "services" in {preset["value"] for preset in listed["presets"]}
    assert "submarines" not in {preset["value"] for preset in listed["presets"]}
    one = client.get(f"{URL}/{row.id}", headers=chief)
    assert one.status_code == 200 and one.json()["key"] == "moliya"


def test_a_direction_never_points_past_the_catalogue(
    client: TestClient, db: Session
) -> None:
    _, chief = _staff(db, email="chief@office.test", superuser=True)

    made_up = client.post(URL, headers=chief, json=_new(preset_key="submarines"))
    assert made_up.status_code == 422
    assert set(made_up.json()["problems"]) == {"preset_key"}
    for key in ("other", "__custom__", "yo'nalish", ""):
        refused = client.post(URL, headers=chief, json=_new(key=key))
        assert refused.status_code == 422, key
        assert set(refused.json()["problems"]) == {"key"}

    assert client.post(URL, headers=chief, json=_new()).status_code == 200
    clash = client.post(URL, headers=chief, json=_new())
    assert clash.json()["problems"] == {"key": "Bu kalit allaqachon bor."}
    assert client.post(URL, headers=chief, json=_new(key="b", label_uz=" ")).json()[
        "problems"
    ] == {"label_uz": "Nomini yozing."}

    row = db.scalar(select(BusinessCategory).where(BusinessCategory.key == "moliya"))
    assert row is not None
    edited = client.put(
        f"{URL}/{row.id}",
        headers=chief,
        json={"label_uz": "Moliya", "preset_key": "submarines"},
    )
    assert edited.status_code == 422


def test_a_broken_direction_is_mended_and_its_profiles_follow(
    client: TestClient, db: Session, queued: list
) -> None:
    """A direction Django left on a preset with no file: every advert refused."""
    auth, user = _ready(client, db)
    chief, boss = _staff(db, email="chief@office.test", superuser=True)
    broken = BusinessCategory(
        key="dengi",
        label_uz="Moliya",
        label_ru="Финансы",
        label_en="Finance",
        preset_key="submarines",
    )
    db.add(broken)
    db.commit()
    saved = client.put("/api/v1/business", json=_profile("dengi"), headers=auth)
    assert saved.status_code == 200, saved.text
    assert _open(client, auth) == (400, "profile_incomplete")

    mended = client.put(
        f"{URL}/{broken.id}",
        headers=boss,
        json={"label_uz": "Moliya", "preset_key": "services", "position": 3},
    )
    assert mended.status_code == 200, mended.text

    business = db.scalar(select(Business).where(Business.user_id == user.id))
    assert business is not None
    db.refresh(business)
    assert business.category == "services"
    assert _open(client, auth)[0] == 200
    resaved = client.put("/api/v1/business", json=_profile("dengi"), headers=auth)
    assert resaved.status_code == 200, resaved.text
    assert resaved.json()["category"] == "services"

    trace = db.scalar(
        select(StaffAction).where(
            StaffAction.owner_id == chief.id,
            StaffAction.kind == ActionKind.DIRECTION_UPDATED,
        )
    )
    assert trace is not None
    assert trace.detail["moved"] == 1
    assert trace.detail["changed"]["Katalog"] == ["submarines", "services"]


def test_a_used_direction_is_switched_off_not_deleted(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, _user = _ready(client, db)
    _, chief = _staff(db, email="chief@office.test", superuser=True)
    made = client.post(URL, headers=chief, json=_new())
    direction_id = made.json()["id"]
    assert (
        client.put("/api/v1/business", json=_profile("moliya"), headers=auth)
    ).status_code == 200

    refused = client.delete(f"{URL}/{direction_id}", headers=chief)
    assert refused.status_code == 400
    assert refused.json()["code"] == "direction_in_use"

    off = client.put(
        f"{URL}/{direction_id}",
        headers=chief,
        json={"label_uz": "Moliya", "preset_key": "services", "is_active": False},
    )
    assert off.status_code == 200, off.text
    picks = client.get("/api/v1/business/choices", headers=auth).json()["categories"]
    assert "moliya" not in {pick["value"] for pick in picks}
    kept = client.put("/api/v1/business", json=_profile("moliya"), headers=auth)
    assert kept.status_code == 200, "the owner keeps a direction switched off later"

    free = client.post(URL, headers=chief, json=_new(key="bosh"))
    assert client.delete(f"{URL}/{free.json()['id']}", headers=chief).status_code == 200
    assert client.get(f"{URL}/{free.json()['id']}", headers=chief).status_code == 404
