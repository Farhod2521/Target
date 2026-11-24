"""A column's buttons against PostgreSQL: what the columns start with, the
superuser's changes (a button added, its column changed, one of their own),
a press reading them, and the way back to the code's own set."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.backoffice.constants import Role
from app.modules.boards import triggers
from app.modules.boards.constants import (
    RENEWAL_ACTIONS,
    SALES_ACTIONS,
    SUPPORT_ACTIONS,
    TicketReason,
)
from app.modules.boards.models import BoardCard
from app.modules.boards.schemas import ButtonsOut, CardDetailOut, ColumnsOut
from app.modules.boards.tickets import raise_ticket
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import _live

URL = "/api/v2/office"


def _view(client: TestClient, head: dict[str, str], board: str) -> ButtonsOut:
    answer = client.get(f"{URL}/boards/{board}/buttons", headers=head)
    assert answer.status_code == 200, answer.text
    return ButtonsOut.model_validate(answer.json())


def _codes(view: ButtonsOut, column: str) -> list[str]:
    return [b.code for b in next(c for c in view.columns if c.code == column).buttons]


def _lead(client: TestClient, db: Session, head: dict[str, str]) -> CardDetailOut:
    _live(db)
    _client(db, f"lead{utcnow().timestamp()}@shop.test")
    triggers.sweep_sales(db, now=utcnow())
    taken = client.post(f"{URL}/sales/take", headers=head)
    assert taken.status_code == 200, taken.text
    return CardDetailOut.model_validate(taken.json())


def _custom_column(
    client: TestClient, head: dict[str, str], board: str, name: str
) -> str:
    answer = client.post(
        f"{URL}/boards/{board}/columns", json={"name": name}, headers=head
    )
    assert answer.status_code == 201, answer.text
    body = ColumnsOut.model_validate(answer.json())
    return next(c.code for c in body.columns if c.name == name)


def test_the_columns_start_with_the_buttons_the_code_gave(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    sales = _view(client, boss, "sales")
    assert sales.may_edit
    for column in sales.columns:
        if column.configurable:
            assert [b.code for b in column.buttons] == [
                str(a) for a in SALES_ACTIONS.get(column.code, ())
            ], column.code
            assert not column.is_changed
            assert all(b.is_default and b.is_default_label for b in column.buttons)
    queue = next(c for c in sales.columns if c.code == "unworked")
    assert not queue.configurable and queue.buttons == []
    assert next(c for c in sales.columns if c.code == "closed").configurable is False
    assert next(c for c in sales.columns if c.code == "discount_20").marks_only
    # What may be changed and what goes where its own rule says.
    talk = next(
        b
        for c in sales.columns
        if c.code == "new_lead"
        for b in c.buttons
        if b.code == "contacted"
    )
    assert not talk.movable and talk.rule_note and talk.default_to == "contacted"
    assert {c.action for c in sales.catalog if c.movable} == {
        "no_contact",
        "callback",
        "will_pay",
        "go",
    }
    # A discount column, a queue and a final one are no place to send a card.
    assert {t.code for t in sales.targets} == {
        "new_lead",
        "no_contact",
        "contacted",
        "callback",
    }

    support = _view(client, boss, "support")
    for column in support.columns:
        if column.configurable:
            assert [b.code for b in column.buttons] == [
                str(a) for a in SUPPORT_ACTIONS.get(column.code, ())
            ]
    new = next(c for c in support.columns if c.code == "new")
    assert not new.configurable and new.fixed == ["Ishlayapman"]
    renewal = _view(client, boss, "renewal")
    for column in renewal.columns:
        if column.configurable:
            assert [b.code for b in column.buttons] == [
                str(a) for a in RENEWAL_ACTIONS.get(column.code, ())
            ]


def test_only_the_superuser_changes_buttons(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    owner = _staff(db, "egasi@office.test", Role.OWNER)
    seller = _staff(db, "ali@office.test", Role.SALES)
    support = _staff(db, "zarina@office.test", Role.SUPPORT)
    path = f"{URL}/boards/sales/buttons"
    view = _view(client, boss, "sales")
    one = next(c for c in view.columns if c.code == "contacted").buttons[0]
    add = {"column": "contacted", "action": "will_pay"}
    edit = {"label": "X", "position": 1}
    for head, refused in ((owner, 403), (seller, 404), (support, 404)):
        assert client.post(path, json=add, headers=head).status_code == refused
        assert (
            client.put(f"{path}/{one.id}", json=edit, headers=head).status_code
            == refused
        )
        assert client.delete(f"{path}/{one.id}", headers=head).status_code == refused
        assert (
            client.post(
                f"{path}/reset", json={"column": "contacted"}, headers=head
            ).status_code
            == refused
        )
    assert not _view(client, owner, "sales").may_edit
    assert client.get(path, headers=support).status_code == 404


def test_a_button_of_the_code_is_added_moved_and_taken_off(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    path = f"{URL}/boards/sales/buttons"
    demo = _custom_column(client, boss, "sales", "Demo")
    card = _lead(client, db, seller)
    press = f"{URL}/cards/{card.id}/actions"
    assert [a.value for a in card.actions] == [
        "contacted",
        "no_contact",
        "callback",
        "close",
    ]

    # «To'laydi» is not on Yangi lead until the superuser puts it there.
    assert (
        client.post(press, json={"action": "will_pay"}, headers=seller).status_code
        == 409
    )
    added = client.post(
        path, json={"column": "new_lead", "action": "will_pay"}, headers=boss
    )
    assert added.status_code == 201, added.text
    assert _codes(ButtonsOut.model_validate(added.json()), "new_lead")[-1] == "will_pay"
    twice = client.post(
        path, json={"column": "new_lead", "action": "will_pay"}, headers=boss
    )
    assert twice.status_code == 422 and twice.json()["code"] == "button_exists"

    # «Vaqt qo'yish» sends the card to the superuser's column, under their words.
    view = _view(client, boss, "sales")
    column = next(c for c in view.columns if c.code == "new_lead")
    assert column.is_changed
    callback = next(b for b in column.buttons if b.code == "callback")
    moved = client.put(
        f"{path}/{callback.id}",
        json={
            "label": "Demo belgilash",
            "to_column": demo,
            "position": callback.position,
        },
        headers=boss,
    )
    assert moved.status_code == 200, moved.text
    seen = CardDetailOut.model_validate(
        client.get(f"{URL}/cards/{card.id}", headers=seller).json()
    )
    button = next(a for a in seen.actions if a.value == "callback")
    assert button.label == "Demo belgilash" and not button.is_default_label
    assert button.due == "required"
    no_time = client.post(press, json={"action": "callback"}, headers=seller)
    assert no_time.status_code == 422 and no_time.json()["code"] == "due_required"
    due = (utcnow() + timedelta(hours=2)).isoformat()
    there = CardDetailOut.model_validate(
        client.post(
            press, json={"action": "callback", "due_at": due}, headers=seller
        ).json()
    )
    assert there.column == demo and there.due_at is not None
    assert there.history[0].kind == "callback" and there.history[0].to_name == "Demo"
    # The column has no buttons of its own yet: the card waits there.
    assert there.actions == []

    # What a button with a rule of its own does is not the superuser's to move.
    talk = next(b for b in column.buttons if b.code == "contacted")
    fixed = client.put(
        f"{path}/{talk.id}",
        json={"to_column": demo, "position": talk.position},
        headers=boss,
    )
    assert fixed.status_code == 422 and fixed.json()["code"] == "button_target_fixed"
    for bad in ("sold", "discount_20", "unworked", "new_lead", "nothing"):
        refused = client.put(
            f"{path}/{callback.id}",
            json={"to_column": bad, "position": callback.position},
            headers=boss,
        )
        assert refused.status_code == 422, bad
        assert refused.json()["code"] == "button_target_invalid", bad

    # Buttons for the new column: one of the code's, and the way back.
    for action in ("no_contact", "close"):
        ok = client.post(path, json={"column": demo, "action": action}, headers=boss)
        assert ok.status_code == 201, ok.text
    again = CardDetailOut.model_validate(
        client.get(f"{URL}/cards/{card.id}", headers=seller).json()
    )
    assert [a.value for a in again.actions] == ["no_contact", "close"]
    missed = CardDetailOut.model_validate(
        client.post(
            f"{URL}/cards/{card.id}/actions",
            json={"action": "no_contact"},
            headers=seller,
        ).json()
    )
    assert missed.column == "no_contact" and missed.attempts == 1

    # Before the column is taken off, the settings say which buttons send
    # cards to it.
    asked = client.get(f"{URL}/boards/sales/columns/{demo}/removal", headers=boss)
    assert asked.status_code == 200, asked.text
    assert len(asked.json()["buttons"]) >= 1

    # «Standartga qaytarish»: the column as the code gives it.
    reset = ButtonsOut.model_validate(
        client.post(f"{path}/reset", json={"column": "new_lead"}, headers=boss).json()
    )
    assert _codes(reset, "new_lead") == [str(a) for a in SALES_ACTIONS["new_lead"]]
    assert not next(c for c in reset.columns if c.code == "new_lead").is_changed
    assert _codes(reset, demo) == ["no_contact", "close"]
    cleared = ButtonsOut.model_validate(
        client.post(f"{path}/reset", json={"column": demo}, headers=boss).json()
    )
    assert _codes(cleared, demo) == []
    gone = client.delete(f"{URL}/boards/sales/columns/{demo}", headers=boss)
    assert gone.status_code == 200, gone.text


def test_a_button_of_the_superusers_own_moves_the_card(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    other = _staff(db, "bobur@office.test", Role.SALES)
    path = f"{URL}/boards/sales/buttons"
    demo = _custom_column(client, boss, "sales", "Demo")
    card = _lead(client, db, seller)
    press = f"{URL}/cards/{card.id}/actions"

    nameless = client.post(
        path,
        json={"column": "new_lead", "action": "go", "to_column": demo},
        headers=boss,
    )
    assert (
        nameless.status_code == 422
        and nameless.json()["code"] == "button_label_required"
    )
    nowhere = client.post(
        path, json={"column": "new_lead", "action": "go", "label": "Demo"}, headers=boss
    )
    assert (
        nowhere.status_code == 422 and nowhere.json()["code"] == "button_target_invalid"
    )
    in_discount = client.post(
        path,
        json={
            "column": "discount_20",
            "action": "go",
            "label": "Demo",
            "to_column": demo,
        },
        headers=boss,
    )
    assert in_discount.status_code == 422
    assert in_discount.json()["code"] == "button_target_fixed"
    queue = client.post(
        path,
        json={"column": "unworked", "action": "go", "label": "Demo", "to_column": demo},
        headers=boss,
    )
    assert queue.status_code == 422 and queue.json()["code"] == "button_column_fixed"
    unknown = client.post(
        path, json={"column": "new_lead", "action": "resolve"}, headers=boss
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_button"

    made = ButtonsOut.model_validate(
        client.post(
            path,
            json={
                "column": "new_lead",
                "action": "go",
                "label": "  Demo   belgilandi ",
                "to_column": demo,
                "due": "optional",
                "note_required": True,
            },
            headers=boss,
        ).json()
    )
    own = next(c for c in made.columns if c.code == "new_lead").buttons[-1]
    assert (
        own.is_custom and own.code.startswith("b_") and own.label == "Demo belgilandi"
    )
    back = ButtonsOut.model_validate(
        client.post(
            path,
            json={
                "column": demo,
                "action": "go",
                "label": "Demo o'tdi",
                "to_column": "contacted",
            },
            headers=boss,
        ).json()
    )
    back_code = _codes(back, demo)[0]

    seen = CardDetailOut.model_validate(
        client.get(f"{URL}/cards/{card.id}", headers=seller).json()
    )
    button = next(a for a in seen.actions if a.value == own.code)
    assert (button.label, button.due, button.note_required, button.reason) == (
        "Demo belgilandi",
        "optional",
        True,
        "",
    )
    assert not button.is_default_label
    bare = client.post(press, json={"action": own.code}, headers=seller)
    assert bare.status_code == 422 and bare.json()["code"] == "note_required"
    # Another manager's card is not theirs to press.
    assert (
        client.post(
            press, json={"action": own.code, "note": "x"}, headers=other
        ).status_code
        == 404
    )

    there = CardDetailOut.model_validate(
        client.post(
            press, json={"action": own.code, "note": "Juma 15:00"}, headers=seller
        ).json()
    )
    assert there.column == demo and there.due_at is None
    assert there.history[0].kind == "button"
    assert there.history[0].body == "Demo belgilandi. Juma 15:00"
    assert [a.value for a in there.actions] == [back_code]
    # The sweep leaves the card where the button put it.
    triggers.sweep_sales(db, now=utcnow())
    db.expire_all()
    assert (
        db.scalar(select(BoardCard.column_code).where(BoardCard.id == card.id)) == demo
    )

    home = CardDetailOut.model_validate(
        client.post(press, json={"action": back_code}, headers=seller).json()
    )
    assert home.column == "contacted" and home.history[0].body == "Demo o'tdi"

    # Taken off: the press finds no such button.
    client.delete(f"{path}/{own.id}", headers=boss)
    card2 = _lead(client, db, seller)
    stale = client.post(
        f"{URL}/cards/{card2.id}/actions",
        json={"action": own.code, "note": "x"},
        headers=seller,
    )
    assert stale.status_code == 409 and stale.json()["code"] == "action_not_here"


def test_a_ticket_goes_through_a_column_of_the_superusers_own(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "ticket@shop.test")
    boss = _staff(db, "boss@office.test", superuser=True)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    dilnoza = _staff(db, "dilnoza@office.test", Role.SUPPORT)
    raise_ticket(
        db, owner_id=owner.id, reason=TicketReason.SETUP, ref="a", now=utcnow()
    )
    db.commit()
    path = f"{URL}/boards/support/buttons"
    bank = _custom_column(client, boss, "support", "Bank javobi kutilmoqda")
    made = client.post(
        path,
        json={
            "column": "in_progress",
            "action": "go",
            "label": "Bankka yuborildi",
            "to_column": bank,
        },
        headers=boss,
    )
    assert made.status_code == 201, made.text
    own = _codes(ButtonsOut.model_validate(made.json()), "in_progress")[-1]
    for action in ("start", "resolve"):
        assert (
            client.post(
                path, json={"column": bank, "action": action}, headers=boss
            ).status_code
            == 201
        )

    taken = CardDetailOut.model_validate(
        client.post(f"{URL}/support/take", headers=zarina).json()
    )
    press = f"{URL}/cards/{taken.id}/actions"
    assert own in [a.value for a in taken.actions]
    held = client.post(press, json={"action": own}, headers=dilnoza)
    assert held.status_code in (404, 409)
    there = CardDetailOut.model_validate(
        client.post(press, json={"action": own}, headers=zarina).json()
    )
    assert there.column == bank and there.manager is not None
    assert [a.value for a in there.actions] == ["start", "resolve"]
    solved = CardDetailOut.model_validate(
        client.post(
            press, json={"action": "resolve", "note": "Bank tasdiqladi"}, headers=zarina
        ).json()
    )
    assert solved.column == "confirming"
    # The queue's own button is the code's, whatever the settings hold.
    view = _view(client, boss, "support")
    assert next(c for c in view.columns if c.code == "new").buttons == []


def test_the_migration_seeds_what_the_code_gives() -> None:
    """Production gets its buttons from migration 0079; a test database from
    ``buttons.ensure``. The two must be the same rows."""
    import importlib.util
    from pathlib import Path

    from app.modules.boards import buttons

    path = next(
        (Path(__file__).parents[2] / "migrations" / "versions").glob("*_0079_*.py")
    )
    spec = importlib.util.spec_from_file_location("m0079", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = [
        (str(board), column, str(action), place)
        for board, columns in buttons.CODE_BUTTONS.items()
        for column in columns
        for place, action in enumerate(buttons._seeds(board, column), start=1)
    ]
    assert list(module.SEEDS) == code
