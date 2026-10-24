"""The sales board against PostgreSQL: the pool's grouping, a card's life."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import utcnow
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.backoffice.constants import Role
from app.modules.public.models import ConsultRequest
from app.modules.sales.models import ContactHold, LostReason, SalesClaim


def _seller(db: Session, *, role: Role = Role.SALES_LEAD) -> dict[str, str]:
    group = db.scalar(select(Group).where(Group.name == str(role)))
    if group is None:
        group = Group(name=str(role))
        db.add(group)
        db.flush()
    seller = User(
        email=f"{role.lower()}@office.test",
        full_name="Seller",
        password="!",
        is_staff=True,
        date_joined=utcnow(),
    )
    db.add(seller)
    db.flush()
    db.add(UserGroup(user_id=seller.id, group_id=group.id))
    db.commit()
    token = tokens.issue(subject=str(seller.id), kind="access", now=utcnow())
    return {"Authorization": f"Bearer {token}"}


def test_pool_card_and_lost_hold(client: TestClient, db: Session) -> None:
    lead = _seller(db)
    newcomer = User(
        email="new@shop.test",
        full_name="Newcomer",
        phone="+998901112233",
        password="!",
        date_joined=utcnow() - timedelta(days=2),
    )
    db.add(newcomer)
    db.add(ConsultRequest(name="Asker", phone_e164="+998907778899", language="uz"))
    reason = LostReason(label="Qimmat", position=1)
    db.add(reason)
    db.commit()

    board = client.get("/api/v1/office/sales", headers=lead)
    assert board.status_code == 200, board.text
    body = board.json()
    chips = {chip["key"]: chip["count"] for chip in body["chips"]}
    assert chips["all"] == 2
    assert chips["ariza"] == 1
    assert chips["new"] == 1
    kinds = {card["name"]: card["group"] for card in body["pool_cards"]}
    assert kinds == {"Newcomer": "new", "Asker": "ariza"}

    found = client.get("/api/v1/office/sales/pool?q=Newc", headers=lead).json()
    assert [card["name"] for card in found["pool_cards"]] == ["Newcomer"]

    taken = client.post(
        f"/api/v1/office/sales/clients/{newcomer.id}/take", headers=lead
    )
    assert taken.status_code == 200, taken.text
    assert taken.json()["mode"] == "own"
    assert taken.json()["placement"]["column"] == "taken"

    again = client.post(
        f"/api/v1/office/sales/clients/{newcomer.id}/take", headers=lead
    ).json()
    assert again["refusal"]

    callback = client.post(
        f"/api/v1/office/sales/clients/{newcomer.id}/outcome",
        headers=lead,
        json={
            "outcome": "callback",
            "callback_at": (utcnow() + timedelta(days=1)).isoformat(),
        },
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["column"] == "callback"

    lost = client.post(
        f"/api/v1/office/sales/clients/{newcomer.id}/outcome",
        headers=lead,
        json={"outcome": "lost", "reason": str(reason.id), "term": "30"},
    )
    assert lost.status_code == 200, lost.text
    assert lost.json()["column"] == "lost"

    db.expire_all()
    claim = db.scalar(select(SalesClaim).where(SalesClaim.owner_id == newcomer.id))
    assert claim is not None and claim.outcome == "lost"
    hold = db.scalar(select(ContactHold).where(ContactHold.owner_id == newcomer.id))
    assert hold is not None and hold.until is not None

    holds = client.get("/api/v1/office/sales/holds", headers=lead).json()
    assert holds["total"] == 1
    reopened = client.post(
        f"/api/v1/office/sales/clients/{newcomer.id}/drop",
        headers=lead,
        json={"to": "taken", "from": "lost"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["column"] == "taken"

    for path in ("/mine", "/team", "/report", "/settings", "/pulse"):
        answer = client.get(f"/api/v1/office/sales{path}", headers=lead)
        assert answer.status_code in (200, 204), (path, answer.text)


def test_request_card_adopted_on_signup(client: TestClient, db: Session) -> None:
    lead = _seller(db)
    consult = ConsultRequest(name="Caller", phone_e164="+998905554433", language="uz")
    db.add(consult)
    db.commit()
    taken = client.post(f"/api/v1/office/sales/clients/{consult.id}/take", headers=lead)
    assert taken.status_code == 200, taken.text
    assert taken.json()["mode"] == "own"

    from app.modules.accounts.services import register_user

    user = register_user(
        db,
        email="caller@shop.test",
        full_name="Caller",
        password="a-long-pass-123",
        phone="+998905554433",
    )
    db.expire_all()
    claim = db.scalar(select(SalesClaim).where(SalesClaim.consult_id == consult.id))
    assert claim is not None and claim.owner_id == user.id


def test_public_consult_and_deletion(client: TestClient) -> None:
    sent = client.post(
        "/api/v1/public/consult", json={"name": " Ali  Vali ", "phone": "+998901234567"}
    )
    assert sent.status_code == 201, sent.text
    asked = client.post(
        "/api/v1/public/data-deletion", json={"email": "Me@Example.com", "reason": ""}
    )
    assert asked.status_code == 201, asked.text
    code = asked.json()["confirmation_code"]
    status = client.get(f"/api/v1/public/data-deletion/status/{code}")
    assert status.json()["is_open"] is True
    home = client.get("/api/v1/public/home")
    assert home.status_code == 200, home.text
