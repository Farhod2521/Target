"""A customer's CRM from their office card, against PostgreSQL with Django's
foreign keys: its figures, staff running the owner's settings, and erasing it."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.audit.constants import ActionType, EventName
from app.modules.audit.models import ActionLog, Event
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.backoffice.schemas import CustomerCrmOut
from app.modules.crm.models import (
    CrmActivity,
    CrmCard,
    CrmLostReason,
    CrmMember,
    CrmSetup,
    CrmStage,
)
from app.modules.leads.models import Lead
from tests.pg.test_crm_http import (
    CRM,
    LATER,
    PASSWORD,
    _auth,
    _member,
    _owner,
    _running,
)

URL = "/api/v1/office/customers"
PAIR = "page_1:act_1"
WHY = "Mijoz so'radi"


def _staff(db: Session, role: Role, email: str) -> dict[str, str]:
    member = User(
        email=email, full_name=email, password="!", is_staff=True, date_joined=utcnow()
    )
    db.add(member)
    db.flush()
    group = db.scalar(select(Group).where(Group.name == str(role)))
    if group is None:
        group = Group(name=str(role))
        db.add(group)
        db.flush()
    db.add(UserGroup(user_id=member.id, group_id=group.id))
    db.commit()
    return _auth(member)


def _crm(client: TestClient, owner: User, head: dict[str, str]) -> dict[str, Any]:
    answer = client.get(f"{URL}/{owner.id}/crm", headers=head)
    assert answer.status_code == 200, answer.text
    return CustomerCrmOut.model_validate(answer.json()).model_dump(mode="json")


def _write(
    client: TestClient,
    owner: User,
    head: dict[str, str],
    path: str,
    body: dict[str, Any] | None = None,
    *,
    method: str = "post",
    pair: str = PAIR,
) -> Any:
    return client.request(
        method,
        f"{URL}/{owner.id}/crm{path}",
        params={"pair": pair},
        headers=head,
        json={"reason": WHY, **(body or {})},
    )


def _kinds(db: Session, owner: User) -> list[str]:
    db.expire_all()
    return [
        row.kind
        for row in db.scalars(
            select(StaffAction)
            .where(StaffAction.owner_id == owner.id)
            .order_by(StaffAction.created_at)
        )
        if row.kind != ActionKind.VIEW
    ]


def _count(db: Session, model: Any, owner: User) -> int:
    db.expire_all()
    return int(
        db.scalar(
            select(func.count()).select_from(model).where(model.owner_id == owner.id)
        )
        or 0
    )


def test_the_card_counts_a_running_crm(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    cards = board["columns"][0]["cards"]
    assert len(cards) == 3
    settings = client.get(f"{CRM}/settings", headers=head).json()
    reason = settings["reasons"][0]["id"]
    won = client.post(
        f"{CRM}/cards/{cards[0]['id']}/win", headers=head, json={"amount": "150"}
    )
    assert won.status_code == 200
    lost = client.post(
        f"{CRM}/cards/{cards[1]['id']}/lose", headers=head, json={"reason": reason}
    )
    assert lost.status_code == 200
    due = client.post(
        f"{CRM}/cards/{cards[2]['id']}/due", headers=head, json={"due": LATER}
    )
    assert due.status_code == 200

    d = _crm(client, owner, _staff(db, Role.SUPPORT, "support@office.test"))

    assert d["pair"] == PAIR
    assert d["setup"]["state"] == "on"
    assert d["enabled_at"] is not None
    f = d["figures"]
    assert (f["leads"], f["cards"], f["open"], f["won"], f["lost"]) == (3, 3, 1, 1, 1)
    assert f["won_minor"] > 0
    assert f["unassigned"] == 1
    assert f["last_activity_at"] is not None
    by_stage = {row["stage_id"]: row for row in f["stages"]}
    first = next(s for s in d["stages"] if s["kind"] == "new")
    assert by_stage[first["id"]]["cards"] == 1
    assert sum(row["cards"] for row in f["stages"]) == 3
    assert [(m["open"], m["won"]) for m in f["managers"]] == [(0, 1)]
    assert f["managers"][0]["won_minor"] == f["won_minor"]
    line = d["pair_lines"][0]
    assert (line["key"], line["state"], line["cards"]) == (PAIR, "on", 3)
    assert d["cards_elsewhere"] == 0
    assert d["totals"]["cards"] == 3
    assert d["totals"]["history"] >= 3
    # The office reads figures, not the customer's leads.
    assert "phone" not in str(d)


def test_a_card_never_set_up_is_empty(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    d = _crm(client, owner, _staff(db, Role.FINANCE, "finance@office.test"))
    assert d["setup"] is None
    assert d["stages"] == []
    assert d["figures"]["leads"] == 3
    assert d["figures"]["cards"] == 0
    assert d["pair_lines"][0]["state"] == "none"
    assert not any(d["totals"].values())


def test_staff_shape_the_columns(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    staff = _staff(db, Role.SUPPORT, "support@office.test")

    added = _write(
        client, owner, staff, "/stages", {"name": "Narx berildi", "color": "#B7791F"}
    )
    assert added.status_code == 200, added.text
    d = _crm(client, owner, staff)
    names = [s["name"] for s in d["stages"]]
    assert names.index("Narx berildi") == names.index("Sotildi") - 1
    fresh = next(s for s in d["stages"] if s["name"] == "Narx berildi")
    won = next(s for s in d["stages"] if s["kind"] == "won")

    edited = _write(
        client,
        owner,
        staff,
        f"/stages/{fresh['id']}",
        {"name": "Narx yuborildi", "color": "#0891B2"},
        method="put",
    )
    assert edited.status_code == 200
    renamed = _write(
        client,
        owner,
        staff,
        f"/stages/{won['id']}",
        {"name": "Yopildi"},
        method="put",
    )
    assert renamed.status_code == 200
    moved = client.post(
        f"{URL}/{owner.id}/crm/stages/{fresh['id']}/move",
        params={"pair": PAIR},
        headers=staff,
        json={"way": "left"},
    )
    assert moved.status_code == 200, moved.text
    d = _crm(client, owner, staff)
    assert [s["name"] for s in d["stages"]][1] == "Narx yuborildi"
    assert next(s for s in d["stages"] if s["id"] == won["id"])["name"] == "Yopildi"

    locked = _write(client, owner, staff, f"/stages/{won['id']}/delete")
    assert locked.status_code == 400
    assert locked.json()["code"] == "stage_locked"
    chosen = _write(client, owner, staff, "/quality", {"quality": [fresh["id"]]})
    assert chosen.status_code == 200
    d = _crm(client, owner, staff)
    assert [s["id"] for s in d["stages"] if s["counts_as_quality"]] == [fresh["id"]]

    gone = _write(client, owner, staff, f"/stages/{fresh['id']}/delete")
    assert gone.status_code == 200
    assert fresh["id"] not in {s["id"] for s in _crm(client, owner, staff)["stages"]}
    assert set(_kinds(db, owner)) == {
        ActionKind.CRM_STAGES_CHANGED,
        ActionKind.CRM_SETTINGS_CHANGED,
    }
    # The customer's own log says the same, under the member of staff.
    log = db.scalars(
        select(ActionLog).where(
            ActionLog.owner_id == owner.id, ActionLog.action == ActionType.CRM_CHANGE
        )
    ).all()
    # Six staff writes above; the wizard's own lines are the owner's.
    assert sum(row.actor_id != owner.id for row in log) == 6


def test_staff_change_how_leads_land(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    _running(client, _auth(owner))
    staff = _staff(db, Role.FINANCE, "finance@office.test")

    assert (
        _write(
            client, owner, staff, "/distribution", {"distribution": "claim"}
        ).status_code
        == 200
    )
    flow = _write(
        client,
        owner,
        staff,
        "/flow",
        {"since": "week", "every_ad": False, "ad": ["ad_1"], "offered": ["ad_1"]},
    )
    assert flow.status_code == 200, flow.text
    added = _write(client, owner, staff, "/reasons", {"name": "Uzoq"})
    assert added.status_code == 200
    d = _crm(client, owner, staff)
    assert d["setup"]["distribution"] == "claim"
    assert d["setup"]["every_ad"] is False
    assert d["setup"]["ad_external_ids"] == ["ad_1"]
    reason = next(r for r in d["reasons"] if r["name"] == "Uzoq")
    assert (
        _write(client, owner, staff, f"/reasons/{reason['id']}/delete").status_code
        == 200
    )
    assert "Uzoq" not in {r["name"] for r in _crm(client, owner, staff)["reasons"]}

    assert _write(client, owner, staff, "/state", {"on": False}).status_code == 200
    assert _crm(client, owner, staff)["setup"]["state"] == "off"
    assert _write(client, owner, staff, "/state", {"on": True}).status_code == 200
    d = _crm(client, owner, staff)
    assert d["setup"]["state"] == "on"
    assert d["figures"]["cards"] == 3
    assert ActionKind.CRM_STATE_CHANGED in _kinds(db, owner)


def test_staff_run_the_sales_managers(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    _running(client, _auth(owner))
    staff = _staff(db, Role.SUPPORT, "support@office.test")

    added = _write(
        client,
        owner,
        staff,
        "/members",
        {
            "name": "Vali",
            "email": "Vali@Example.com",
            "password": PASSWORD,
            "kpi_fix": "3 000 000",
            "kpi_percent": "5",
        },
    )
    assert added.status_code == 200, added.text
    d = _crm(client, owner, staff)
    member = d["members"][0]
    assert member["user"]["email"] == "vali@example.com"
    assert member["must_change_password"] is True
    assert member["kpi_percent"] == 5
    assert d["seats"]["used"] == 1
    login = client.post(
        "/api/v1/auth/login", json={"email": "vali@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200

    taken = _write(
        client,
        owner,
        staff,
        "/members",
        {"name": "Yana", "email": "vali@example.com", "password": PASSWORD},
    )
    assert taken.status_code == 400
    assert taken.json()["code"] == "email_taken"
    weak = _write(
        client,
        owner,
        staff,
        "/members",
        {"name": "Yana", "email": "yana@example.com", "password": "1"},
    )
    assert weak.status_code == 400

    edited = _write(
        client,
        owner,
        staff,
        f"/members/{member['id']}",
        {"name": "Vali K", "takes_leads": False},
        method="put",
    )
    assert edited.status_code == 200
    d = _crm(client, owner, staff)
    assert d["members"][0]["user"]["full_name"] == "Vali K"
    assert d["members"][0]["takes_leads"] is False
    assert d["members"][0]["kpi_percent"] is None

    fresh = "Zk8$nR3wMq6x"
    assert (
        _write(
            client,
            owner,
            staff,
            f"/members/{member['id']}/password",
            {"password": fresh},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "vali@example.com", "password": fresh}
        ).status_code
        == 200
    )
    journal = db.scalars(
        select(StaffAction).where(StaffAction.owner_id == owner.id)
    ).all()
    assert fresh not in str([row.detail for row in journal])
    assert PASSWORD not in str([row.detail for row in journal])

    gone = _write(client, owner, staff, f"/members/{member['id']}/delete")
    assert gone.status_code == 200
    assert _crm(client, owner, staff)["members"] == []
    assert db.scalar(select(User).where(User.email == "vali@example.com")) is None


def test_a_write_keeps_to_its_pair(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    _running(client, _auth(owner))
    staff = _staff(db, Role.SUPPORT, "support@office.test")

    left = _write(client, owner, staff, "/stages", {"name": "X"}, pair="page_9:act_9")
    assert left.status_code == 404
    missing = client.post(
        f"{URL}/{owner.id}/crm/stages",
        headers=staff,
        json={"name": "X", "reason": WHY},
    )
    assert missing.status_code == 422
    blank = client.post(
        f"{URL}/{owner.id}/crm/stages",
        params={"pair": PAIR},
        headers=staff,
        json={"name": "X", "reason": "   "},
    )
    assert blank.status_code == 422


def test_the_office_door(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    other = _auth(owner)
    _running(client, other)
    sales = _staff(db, Role.SALES, "sales@office.test")
    for head in (sales, other):
        assert client.get(f"{URL}/{owner.id}/crm", headers=head).status_code == 404
        assert _write(client, owner, head, "/stages", {"name": "X"}).status_code == 404
    support = _staff(db, Role.SUPPORT, "support@office.test")
    assert (
        _write(client, owner, support, "/erase", {"email": owner.email}).status_code
        == 404
    )
    assert _count(db, CrmCard, owner) == 3


def test_erasing_takes_the_whole_crm_and_keeps_the_leads(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    member, manager = _member(client, head, "vali@example.com")
    cards = list(db.scalars(select(CrmCard).where(CrmCard.owner_id == owner.id)))
    assigned = client.post(
        f"{CRM}/cards/{cards[0].id}/assign",
        headers=head,
        json={"assignee": member["user"]["id"]},
    )
    assert assigned.status_code == 200
    boss = _staff(db, Role.OWNER, "boss@office.test")

    wrong = _write(client, owner, boss, "/erase", {"email": "boshqa@example.com"})
    assert wrong.status_code == 400
    assert _count(db, CrmCard, owner) == 3

    done = _write(client, owner, boss, "/erase", {"email": " CRM@example.com "})
    assert done.status_code == 200, done.text
    assert "3 ta karta" in done.json()["message"]

    for model in (CrmCard, CrmActivity, CrmStage, CrmLostReason, CrmMember, CrmSetup):
        assert _count(db, model, owner) == 0, model
    assert db.scalar(select(User).where(User.email == "vali@example.com")) is None
    assert _count(db, Lead, owner) == 3
    assert client.get(CRM, headers=manager).status_code == 401
    row = db.scalar(
        select(StaffAction).where(
            StaffAction.owner_id == owner.id,
            StaffAction.kind == ActionKind.CRM_ERASED,
        )
    )
    assert row is not None
    assert row.reason == WHY
    assert (row.detail["cards"], row.detail["managers"]) == (3, 1)
    assert db.scalar(
        select(Event).where(
            Event.owner_id == owner.id, Event.name == EventName.CRM_ERASED
        )
    )

    # As if it was never set up: the customer meets the wizard, and can walk it.
    board = client.get(CRM, headers=head).json()
    assert board["setup_needed"] is True
    assert board["step"] == 1
    _running(client, head)
    assert _count(db, CrmCard, owner) == 3
