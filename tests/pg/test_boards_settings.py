"""Office boards v2 settings against PostgreSQL: renaming and reordering
columns, moving a card by hand, and staff with their roles."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.backoffice.models import StaffAction
from app.modules.boards import triggers
from app.modules.boards.constants import TicketReason
from app.modules.boards.schemas import (
    CardDetailOut,
    ColumnsOut,
    StaffPeopleOut,
    StaffPersonOut,
)
from app.modules.boards.tickets import raise_ticket
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import _live

URL = "/api/v2/office"


def _codes(answer: object) -> list[tuple[str, str]]:
    body = ColumnsOut.model_validate(answer.json())  # type: ignore[attr-defined]
    return [(c.code, c.name) for c in body.columns]


def test_the_superuser_renames_and_reorders_columns(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)
    path = f"{URL}/boards/support/columns"
    client.get(path, headers=boss)

    saved = client.patch(
        path,
        json={
            "columns": [
                {"code": "in_progress", "name": "  Jarayonda "},
                {"code": "new", "name": "Kelgan"},
                {"code": "resolved", "name": "Tayyor"},
            ]
        },
        headers=boss,
    )
    assert saved.status_code == 200, saved.text
    assert _codes(saved) == [
        ("in_progress", "Jarayonda"),
        ("new", "Kelgan"),
        ("resolved", "Tayyor"),
    ]

    missing = client.patch(
        path, json={"columns": [{"code": "new", "name": "X"}]}, headers=boss
    )
    assert missing.status_code == 422 and missing.json()["code"] == "columns_mismatch"
    twice = client.patch(
        path,
        json={"columns": [{"code": "new", "name": "A"}] * 3},
        headers=boss,
    )
    assert twice.status_code == 422
    blank = client.patch(
        path,
        json={
            "columns": [
                {"code": "in_progress", "name": "   "},
                {"code": "new", "name": "B"},
                {"code": "resolved", "name": "C"},
            ]
        },
        headers=boss,
    )
    assert blank.status_code == 422
    sales = client.patch(
        f"{URL}/boards/sales/columns", json={"columns": []}, headers=lead
    )
    assert sales.status_code == 404


def test_hidden_columns_stay_hidden_and_after_the_visible_ones(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    path = f"{URL}/boards/sales/columns"
    shown = _codes(client.get(path, headers=boss))
    order = list(reversed(shown))

    saved = client.patch(
        path, json={"columns": [{"code": c, "name": n} for c, n in order]}, headers=boss
    )
    assert _codes(saved) == order
    from app.modules.boards.models import BoardColumn

    hidden = list(
        db.scalars(
            select(BoardColumn.position).where(
                BoardColumn.board == "sales", BoardColumn.is_visible.is_(False)
            )
        )
    )
    assert min(hidden) > len(order)


def test_the_superuser_moves_a_card_by_hand_with_a_reason(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "move@shop.test")
    triggers.sweep_sales(db, now=utcnow())
    raise_ticket(
        db, owner_id=owner.id, reason=TicketReason.SETUP, ref="a", now=utcnow()
    )
    db.commit()
    from app.modules.boards.models import BoardCard

    sales = db.scalar(select(BoardCard).where(BoardCard.board == "sales"))
    ticket = db.scalar(select(BoardCard).where(BoardCard.board == "support"))
    assert sales is not None and ticket is not None
    boss = _staff(db, "boss@office.test", superuser=True)
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)

    no_reason = client.post(
        f"{URL}/cards/{sales.id}/move",
        json={"column": "closed", "reason": " "},
        headers=boss,
    )
    assert no_reason.status_code == 422
    hidden = client.post(
        f"{URL}/cards/{sales.id}/move",
        json={"column": "trial", "reason": "x"},
        headers=boss,
    )
    assert hidden.status_code == 422 and hidden.json()["code"] == "no_such_column"
    other_board = client.post(
        f"{URL}/cards/{sales.id}/move",
        json={"column": "resolved", "reason": "x"},
        headers=boss,
    )
    assert other_board.status_code == 422
    assert (
        client.post(
            f"{URL}/cards/{sales.id}/move",
            json={"column": "closed", "reason": "x"},
            headers=lead,
        ).status_code
        == 404
    )

    closed = CardDetailOut.model_validate(
        client.post(
            f"{URL}/cards/{sales.id}/move",
            json={"column": "closed", "reason": "Dublikat"},
            headers=boss,
        ).json()
    )
    assert closed.column == "closed" and closed.closed_at is not None
    assert closed.history[0].kind == "moved" and closed.history[0].body == "Dublikat"
    opened = CardDetailOut.model_validate(
        client.post(
            f"{URL}/cards/{sales.id}/move",
            json={"column": "contacted", "reason": "Xato yopilgan"},
            headers=boss,
        ).json()
    )
    assert opened.column == "contacted" and opened.closed_at is None

    solved = CardDetailOut.model_validate(
        client.post(
            f"{URL}/cards/{ticket.id}/move",
            json={"column": "resolved", "reason": "Telefonda hal qilindi"},
            headers=boss,
        ).json()
    )
    assert solved.column == "resolved" and solved.closed_at is not None


def test_staff_are_found_added_given_roles_and_taken_off(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    owner_head = _staff(db, "egasi@office.test", Role.OWNER)
    support = _staff(db, "support@office.test", Role.SUPPORT)
    newcomer = _client(db, "yangi.xodim@shop.test")
    login_owner = _client(db, "biznes@shop.test")
    _client(db, "crm.login@shop.test", crm_owner_id=login_owner.id)

    found = StaffPeopleOut.model_validate(
        client.get(f"{URL}/staff/search", params={"q": "xodim"}, headers=boss).json()
    )
    assert [p.email for p in found.people] == ["yangi.xodim@shop.test"]
    crm = client.get(
        f"{URL}/staff/search", params={"q": "crm.login"}, headers=boss
    ).json()
    assert crm["people"] == []
    assert (
        client.get(
            f"{URL}/staff/search", params={"q": "xodim"}, headers=support
        ).status_code
        == 404
    )

    added = client.post(
        f"{URL}/staff",
        json={"user_id": str(newcomer.id), "roles": ["Sales"]},
        headers=owner_head,
    )
    assert added.status_code == 201, added.text
    person = StaffPersonOut.model_validate(added.json())
    assert person.is_staff and [r.value for r in person.roles] == ["Sales"]
    me = client.get(f"{URL}/me", headers=_staff_head(db, newcomer)).json()
    assert [b["code"] for b in me["boards"]] == ["sales"]

    again = client.post(
        f"{URL}/staff", json={"user_id": str(newcomer.id), "roles": []}, headers=boss
    )
    assert again.status_code >= 400
    owner_grant = client.patch(
        f"{URL}/staff/{newcomer.id}", json={"roles": ["Owner"]}, headers=owner_head
    )
    assert (
        owner_grant.status_code == 403
        and owner_grant.json()["code"] == "owner_role_superuser_only"
    )
    unknown = client.patch(
        f"{URL}/staff/{newcomer.id}", json={"roles": ["Boss"]}, headers=boss
    )
    assert unknown.status_code == 422

    both = StaffPersonOut.model_validate(
        client.patch(
            f"{URL}/staff/{newcomer.id}",
            json={"roles": ["SalesLead", "Support"]},
            headers=boss,
        ).json()
    )
    assert sorted(r.value for r in both.roles) == ["SalesLead", "Support"]

    listed = StaffPeopleOut.model_validate(
        client.get(f"{URL}/staff", headers=boss).json()
    )
    assert {p.email for p in listed.people} >= {
        "boss@office.test",
        "yangi.xodim@shop.test",
    }
    assert listed.people[0].is_superuser

    me_id = db.scalar(select(User.id).where(User.email == "egasi@office.test"))
    own = client.patch(f"{URL}/staff/{me_id}", json={"roles": []}, headers=owner_head)
    assert own.status_code >= 400

    assert client.delete(f"{URL}/staff/{newcomer.id}", headers=boss).status_code == 204
    db.expire_all()
    gone = db.get(User, newcomer.id)
    assert gone is not None and not gone.is_staff
    kinds = {
        a.kind
        for a in db.scalars(
            select(StaffAction).where(StaffAction.owner_id == newcomer.id)
        )
    }
    assert {"staff_added", "roles_changed", "staff_removed"} <= kinds


def _staff_head(db: Session, user: User) -> dict[str, str]:
    from tests.pg.test_crm_http import _auth

    db.expire_all()
    fresh = db.get(User, user.id)
    assert fresh is not None
    return _auth(fresh)
