"""The office's shell and journal: who sees which door, what the log holds."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import utcnow
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.backoffice.selectors import traces
from app.modules.supportchat.models import SupportConversation


def _staff(db: Session, *roles: Role, email: str) -> tuple[User, dict[str, str]]:
    member = User(
        email=email, full_name=email, password="!", is_staff=True, date_joined=utcnow()
    )
    db.add(member)
    db.flush()
    for role in roles:
        group = db.scalar(select(Group).where(Group.name == str(role)))
        if group is None:
            group = Group(name=str(role))
            db.add(group)
            db.flush()
        db.add(UserGroup(user_id=member.id, group_id=group.id))
    db.commit()
    token = tokens.issue(subject=str(member.id), kind="access", now=utcnow())
    return member, {"Authorization": f"Bearer {token}"}


def _customer(db: Session) -> User:
    customer = User(
        email="shop@client.test", full_name="Shop", password="!", date_joined=utcnow()
    )
    db.add(customer)
    db.commit()
    return customer


def test_me_draws_only_the_doors_a_role_opens(client: TestClient, db: Session) -> None:
    customer = _customer(db)
    db.add(SupportConversation(owner_id=customer.id, last_client_at=utcnow()))
    db.commit()
    _, seller = _staff(db, Role.SALES, email="seller@office.test")
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    sold = client.get("/api/v1/office/me", headers=seller)
    assert sold.status_code == 200, sold.text
    body = sold.json()
    assert [role["value"] for role in body["roles"]] == ["Sales"]
    assert body["can"]["sell"] and not body["can"]["give"]
    assert body["waiting"]["support"] == 0

    answered = client.get("/api/v1/office/me", headers=support).json()
    assert answered["can"]["give"] and answered["can"]["answer_support"]
    assert not answered["can"]["grant"] and not answered["can"]["owner"]
    assert answered["waiting"]["support"] == 1


def test_me_and_journal_refuse_with_404(client: TestClient, db: Session) -> None:
    _, bare = _staff(db, email="bare@office.test")
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    customer = _customer(db)
    token = tokens.issue(subject=str(customer.id), kind="access", now=utcnow())

    assert client.get("/api/v1/office/me", headers=bare).status_code == 404
    assert (
        client.get(
            "/api/v1/office/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/office/journal", headers=support).status_code == 404


def test_journal_hides_readings_unless_asked(client: TestClient, db: Session) -> None:
    owner, headers = _staff(db, Role.OWNER, email="owner@office.test")
    customer = _customer(db)
    now = utcnow()
    db.add_all(
        [
            StaffAction(
                owner_id=customer.id,
                actor_id=owner.id,
                kind=str(ActionKind.VIEW),
                created_at=now - timedelta(minutes=2),
            ),
            StaffAction(
                owner_id=customer.id,
                actor_id=owner.id,
                kind=str(ActionKind.DAYS_GRANTED),
                reason="Sovg'a",
                detail={"days": 7},
                created_at=now - timedelta(minutes=1),
            ),
        ]
    )
    db.commit()

    page = client.get("/api/v1/office/journal", headers=headers)
    assert page.status_code == 200, page.text
    body = page.json()
    assert [row["kind"] for row in body["rows"]] == ["days_granted"]
    assert body["rows"][0]["kind_label"] == "Kun berildi"
    assert body["rows"][0]["customer"]["email"] == "shop@client.test"
    assert body["rows"][0]["actor"]["email"] == "owner@office.test"
    assert body["kinds"][0] == {"value": "", "label": "Amallar"}
    assert not body["has_more"]

    readings = client.get("/api/v1/office/journal?kind=view", headers=headers).json()
    assert [row["kind"] for row in readings["rows"]] == ["view"]

    assert [row.kind for row in traces(db, owner=customer)] == [
        "days_granted",
        "view",
    ]
