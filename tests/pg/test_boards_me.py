"""The office boards v2 against PostgreSQL: who opens which board, the
columns each person sees, and the board's live moment written once."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.backoffice.constants import Role
from app.modules.boards import selectors
from app.modules.boards.constants import SEED_COLUMNS, Board
from app.modules.boards.models import BoardColumn, BoardSetting
from app.modules.boards.schemas import ColumnsOut, MeOut
from tests.pg.conftest import sign_up
from tests.pg.test_crm_http import _auth

ME = "/api/v2/office/me"


def _staff(
    db: Session, email: str, *roles: Role, superuser: bool = False
) -> dict[str, str]:
    member = User(
        email=email,
        full_name=email,
        password="!",
        is_staff=True,
        is_superuser=superuser,
        date_joined=utcnow(),
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
    return _auth(member)


def _columns(client: TestClient, board: str, head: dict[str, str]) -> list[str]:
    answer = client.get(f"/api/v2/office/boards/{board}/columns", headers=head)
    assert answer.status_code == 200, answer.text
    return [column.code for column in ColumnsOut.model_validate(answer.json()).columns]


def test_a_sales_manager_opens_sales_and_is_refused_support(
    client: TestClient, db: Session
) -> None:
    head = _staff(db, "sotuv@example.com", Role.SALES)

    me = MeOut.model_validate(client.get(ME, headers=head).json())
    assert [board.code for board in me.boards] == ["sales"]
    assert me.default_board == "sales"
    assert me.can.take and not me.can.assign and not me.can.move

    assert _columns(client, "sales", head) == [
        "new_lead",
        "no_contact",
        "contacted",
        "callback",
        "discount_20",
        "discount_10",
        "no_discount",
        "awaiting",
        "sold",
    ]
    refused = client.get("/api/v2/office/boards/support/columns", headers=head)
    assert refused.status_code == 404


def test_the_sales_lead_also_sees_unworked_and_closed(
    client: TestClient, db: Session
) -> None:
    head = _staff(db, "rahbar@example.com", Role.SALES_LEAD)

    me = MeOut.model_validate(client.get(ME, headers=head).json())
    assert me.boards[0].lead and me.can.assign and not me.can.columns
    assert _columns(client, "sales", head) == [
        "unworked",
        "new_lead",
        "no_contact",
        "contacted",
        "callback",
        "discount_20",
        "discount_10",
        "no_discount",
        "awaiting",
        "sold",
        "closed",
    ]


def test_support_opens_only_support(client: TestClient, db: Session) -> None:
    head = _staff(db, "support@example.com", Role.SUPPORT)

    me = MeOut.model_validate(client.get(ME, headers=head).json())
    assert [board.code for board in me.boards] == ["support"]
    assert not me.can.take and me.can.take_ticket
    assert _columns(client, "support", head) == [
        "new",
        "in_progress",
        "waiting",
        "developer",
        "confirming",
        "resolved",
        "closed",
    ]
    assert (
        client.get("/api/v2/office/boards/sales/columns", headers=head).status_code
        == 404
    )


def test_the_superuser_opens_both_and_may_change_them(
    client: TestClient, db: Session
) -> None:
    head = _staff(db, "boss@example.com", superuser=True)

    me = MeOut.model_validate(client.get(ME, headers=head).json())
    assert [board.code for board in me.boards] == ["sales", "support"]
    assert me.can.move and me.can.columns and me.can.staff
    assert len(_columns(client, "sales", head)) == 11


def test_staff_without_a_board_get_none_and_customers_get_404(
    client: TestClient, db: Session
) -> None:
    finance = _staff(db, "pul@example.com", Role.FINANCE)
    me = MeOut.model_validate(client.get(ME, headers=finance).json())
    assert me.boards == [] and me.default_board is None
    assert (
        client.get("/api/v2/office/boards/sales/columns", headers=finance).status_code
        == 404
    )

    customer = sign_up(client)
    assert client.get(ME, headers=customer).status_code == 404
    assert (
        client.get("/api/v2/office/boards/sales/columns", headers=customer).status_code
        == 404
    )
    assert client.get(ME).status_code in (401, 403)


def test_an_unknown_board_is_404(client: TestClient, db: Session) -> None:
    head = _staff(db, "boss@example.com", superuser=True)

    assert (
        client.get("/api/v2/office/boards/finance/columns", headers=head).status_code
        == 404
    )


def test_the_live_moment_and_the_columns_are_written_once(db: Session) -> None:
    first = utcnow()
    selectors.ensure_board(db, board=Board.SALES, now=first)
    db.commit()
    selectors.ensure_board(db, board=Board.SALES, now=utcnow())
    db.commit()

    assert (
        db.scalar(select(BoardSetting.live_since).where(BoardSetting.board == "sales"))
        == first
    )
    count = db.scalar(
        select(func.count())
        .select_from(BoardColumn)
        .where(BoardColumn.board == "sales")
    )
    assert count == sum(1 for seed in SEED_COLUMNS if seed.board == Board.SALES)


def test_a_new_seed_column_goes_after_the_office_order(db: Session) -> None:
    selectors.ensure_board(db, board=Board.SUPPORT, now=utcnow())
    db.commit()
    resolved = db.scalar(select(BoardColumn).where(BoardColumn.code == "resolved"))
    assert resolved is not None
    db.delete(resolved)
    db.commit()

    selectors.ensure_board(db, board=Board.SUPPORT, now=utcnow())
    db.commit()

    back = db.scalar(select(BoardColumn).where(BoardColumn.code == "resolved"))
    assert back is not None and back.position == 8
