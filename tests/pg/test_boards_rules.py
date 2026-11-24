"""The boards' automatic rules against PostgreSQL: what the settings show,
what the superuser may change of a rule the code runs (and what not), the
reason a move writes, rules of the superuser's own, and who may."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.backoffice.constants import Role
from app.modules.boards import rules, triggers
from app.modules.boards.constants import TicketReason
from app.modules.boards.models import BoardCard
from app.modules.boards.schemas import (
    BoardViewOut,
    CardDetailOut,
    ColumnsOut,
    RulesOut,
)
from app.modules.boards.tickets import raise_ticket
from tests.pg.test_boards_deadlines import _bill
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import _live

URL = "/api/v2/office"


def _view(client: TestClient, head: dict[str, str], board: str) -> RulesOut:
    answer = client.get(f"{URL}/boards/{board}/rules", headers=head)
    assert answer.status_code == 200, answer.text
    return RulesOut.model_validate(answer.json())


def _rule(view: RulesOut, code: str):
    return next(rule for rule in view.rules if rule.code == code)


def _lead(client: TestClient, db: Session, head: dict[str, str]):
    _live(db)
    owner = _client(db, f"lead{utcnow().timestamp()}@shop.test")
    triggers.sweep_sales(db, now=utcnow())
    taken = client.post(f"{URL}/sales/take", headers=head)
    assert taken.status_code == 200, taken.text
    return CardDetailOut.model_validate(taken.json()), owner


def _card(client: TestClient, head: dict[str, str], card_id: str) -> CardDetailOut:
    return CardDetailOut.model_validate(
        client.get(f"{URL}/cards/{card_id}", headers=head).json()
    )


def _custom_column(
    client: TestClient, head: dict[str, str], board: str, name: str
) -> str:
    answer = client.post(
        f"{URL}/boards/{board}/columns", json={"name": name}, headers=head
    )
    assert answer.status_code == 201, answer.text
    body = ColumnsOut.model_validate(answer.json())
    return next(c.code for c in body.columns if c.name == name)


def test_every_rule_of_the_code_is_shown_with_what_may_be_changed(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    sales = _view(client, boss, "sales")
    assert sales.may_edit
    assert [r.code for r in sales.rules] == [
        s.code for s in rules.SPECS if str(s.board) == "sales"
    ]
    assert all(r.id and not r.is_custom and not r.is_changed for r in sales.rules)
    # Money is the code's: only the words a move writes may be reworded.
    for code in (
        "sales.sold",
        "sales.start_bought",
        "sales.offer_step",
        "sales.offer_ended",
    ):
        assert _rule(sales, code).editable == ["reason"], code
    bill = _rule(sales, "sales.bill_opened")
    assert bill.editable == ["enabled", "from", "reason", "to"]
    assert bill.to_column == "awaiting" and "new_lead" in bill.from_columns
    assert "«To'lov kutilmoqda»" in bill.sentence and "«Yangi lead»" in bill.sentence
    # A discount column, a queue and a final one are not read from or sent to.
    assert {c.code for c in sales.from_choices} == {
        "new_lead",
        "no_contact",
        "contacted",
        "callback",
        "awaiting",
    }
    assert {c.code for c in sales.to_choices} == {
        "new_lead",
        "no_contact",
        "contacted",
        "callback",
    }

    support = _view(client, boss, "support")
    setup = _rule(support, "support.setup_late")
    assert (setup.amount, setup.unit, setup.editable) == (
        60,
        "minutes",
        ["amount", "enabled"],
    )
    assert "60 daqiqa" in setup.sentence
    renewal = _view(client, boss, "renewal")
    assert (
        _rule(renewal, "renewal.opened").amount,
        _rule(renewal, "renewal.silent").amount,
    ) == (3, 30)
    assert len(sales.rules) + len(support.rules) + len(renewal.rules) == len(
        rules.SPECS
    )


def test_only_the_superuser_changes_rules(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    owner = _staff(db, "egasi@office.test", Role.OWNER)
    seller = _staff(db, "ali@office.test", Role.SALES)
    support = _staff(db, "zarina@office.test", Role.SUPPORT)
    path = f"{URL}/boards/sales/rules"
    one = _rule(_view(client, boss, "sales"), "sales.bill_opened")
    new = {
        "kind": "stay",
        "name": "X",
        "from_columns": ["contacted"],
        "to_column": "callback",
        "amount": 2,
        "unit": "days",
    }
    for head, refused in ((owner, 403), (seller, 404), (support, 404)):
        assert client.post(path, json=new, headers=head).status_code == refused
        assert (
            client.patch(
                f"{path}/{one.id}", json={"is_enabled": False}, headers=head
            ).status_code
            == refused
        )
        assert (
            client.post(f"{path}/{one.id}/reset", headers=head).status_code == refused
        )
        assert client.delete(f"{path}/{one.id}", headers=head).status_code == refused
    read = _view(client, owner, "sales")
    assert not read.may_edit and len(read.rules) == 9
    assert client.get(path, headers=support).status_code == 404


def test_a_bill_rule_reads_the_superusers_columns_and_writes_its_reason(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    demo = _custom_column(client, boss, "sales", "Demo")
    path = f"{URL}/boards/sales/rules"
    card, owner = _lead(client, db, seller)
    one = _rule(_view(client, boss, "sales"), "sales.bill_opened")

    # By default a card in a column of the superuser's own is not the rule's.
    client.post(
        f"{URL}/cards/{card.id}/move",
        json={"column": demo, "reason": "Demo"},
        headers=boss,
    )
    bill = _bill(db, owner)
    triggers.sweep_sales(db, now=utcnow())
    assert _card(client, seller, card.id).column == demo

    changed = client.patch(
        f"{path}/{one.id}",
        json={
            "from_columns": [*one.from_columns, demo],
            "reason": "Mijoz hisob ochdi — to'lovni kuting",
        },
        headers=boss,
    )
    assert changed.status_code == 200, changed.text
    seen = _rule(RulesOut.model_validate(changed.json()), "sales.bill_opened")
    assert seen.is_changed and demo in seen.from_columns and "«Demo»" in seen.sentence
    triggers.sweep_sales(db, now=utcnow())
    waiting = _card(client, seller, card.id)
    assert waiting.column == "awaiting"
    assert waiting.history[0].kind == "bill_opened"
    assert waiting.history[0].body == (
        "Mijoz hisob ochdi — to'lovni kuting: №TA-BILL, 490 000 UZS"
    )
    # The card's face says why it stands there.
    assert waiting.why is not None and waiting.why.auto
    assert waiting.why.body == waiting.history[0].body
    board = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/sales", headers=boss).json()
    )
    face = next(c for col in board.columns for c in col.cards if c.id == card.id)
    assert face.why is not None and face.why.kind == "bill_opened" and face.why.auto

    # The bill left unpaid: back to the superuser's column, with the reason.
    unpaid = _rule(_view(client, boss, "sales"), "sales.bill_unpaid")
    client.patch(f"{path}/{unpaid.id}", json={"to_column": demo}, headers=boss)
    bill.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    triggers.sweep_sales(db, now=utcnow())
    late = _card(client, seller, card.id)
    assert late.column == demo and late.overdue
    assert (
        late.history[0].body
        == "Mijoz ochgan hisobni to'lamadi, qo'ng'iroq qilish kerak."
    )

    # Before the column is taken off, the settings name the rules that use it.
    client.post(
        f"{URL}/cards/{card.id}/move",
        json={"column": "contacted", "reason": "x"},
        headers=boss,
    )
    asked = client.get(f"{URL}/boards/sales/columns/{demo}/removal", headers=boss)
    assert asked.status_code == 200, asked.text
    assert set(asked.json()["rules"]) == {"Mijoz hisob ochdi", "Hisob to'lanmadi"}

    # «Standartga qaytarish» gives the rule back as the code has it.
    for rule_id in (one.id, unpaid.id):
        assert client.post(f"{path}/{rule_id}/reset", headers=boss).status_code == 200
    back = _view(client, boss, "sales")
    assert not _rule(back, "sales.bill_opened").is_changed
    assert _rule(back, "sales.bill_unpaid").to_column == "callback"
    assert (
        client.delete(f"{URL}/boards/sales/columns/{demo}", headers=boss).status_code
        == 200
    )


def test_a_rule_switched_off_does_nothing_and_fixed_parts_stay_fixed(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    path = f"{URL}/boards/sales/rules"
    card, owner = _lead(client, db, seller)
    view = _view(client, boss, "sales")
    one = _rule(view, "sales.bill_opened")

    off = client.patch(f"{path}/{one.id}", json={"is_enabled": False}, headers=boss)
    assert off.status_code == 200, off.text
    _bill(db, owner)
    triggers.sweep_sales(db, now=utcnow())
    assert _card(client, seller, card.id).column == "new_lead"
    client.patch(f"{path}/{one.id}", json={"is_enabled": True}, headers=boss)
    triggers.sweep_sales(db, now=utcnow())
    assert _card(client, seller, card.id).column == "awaiting"

    # The sale is the code's: its words may change, nothing else.
    sold = _rule(view, "sales.sold")
    for body in ({"is_enabled": False}, {"to_column": "contacted"}, {"amount": 5}):
        refused = client.patch(f"{path}/{sold.id}", json=body, headers=boss)
        assert refused.status_code == 422, body
        assert refused.json()["code"] == "rule_field_fixed", body
    worded = client.patch(
        f"{path}/{sold.id}", json={"reason": "Pul tushdi"}, headers=boss
    )
    assert (
        _rule(RulesOut.model_validate(worded.json()), "sales.sold").reason
        == "Pul tushdi"
    )
    # Where a rule may not read from or send to.
    for body in (
        {"to_column": "sold"},
        {"to_column": "discount_20"},
        {"to_column": "nothing"},
        {"from_columns": ["discount_20"]},
        {"from_columns": ["unworked"]},
        {"from_columns": ["closed"]},
        {"from_columns": []},
        {"from_columns": ["awaiting"]},
    ):
        refused = client.patch(f"{path}/{one.id}", json=body, headers=boss)
        assert refused.status_code == 422, body
        assert refused.json()["code"] == "rule_invalid", body
    assert client.delete(f"{path}/{one.id}", headers=boss).status_code == 422


def test_a_ticket_rule_waits_as_long_as_the_superuser_says(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    path = f"{URL}/boards/support/rules"
    view = _view(client, boss, "support")
    setup = _rule(view, "support.setup_late")
    waited = client.patch(f"{path}/{setup.id}", json={"amount": 180}, headers=boss)
    assert waited.status_code == 200, waited.text
    assert rules.get(db, "support.setup_late").delta == timedelta(minutes=180)
    assert (
        "180 daqiqa"
        in _rule(RulesOut.model_validate(waited.json()), "support.setup_late").sentence
    )
    client.patch(f"{path}/{setup.id}", json={"is_enabled": False}, headers=boss)
    assert rules.get(db, "support.setup_late").enabled is False
    # Switched off: the sweep opens no such ticket.
    _live(db)
    assert triggers.setup_late(db, now=utcnow()) == 0
    zero = client.patch(f"{path}/{setup.id}", json={"amount": 0}, headers=boss)
    assert zero.status_code == 422


def test_a_rule_of_the_superusers_own_moves_a_card_that_stood_too_long(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    path = f"{URL}/boards/sales/rules"
    cold = _custom_column(client, boss, "sales", "Sovuq")
    card, _ = _lead(client, db, seller)
    client.post(
        f"{URL}/cards/{card.id}/actions", json={"action": "no_contact"}, headers=seller
    )

    def new(**more):
        return {
            "kind": "stay",
            "name": "Uch kun javobsiz",
            "from_columns": ["no_contact"],
            "to_column": cold,
            "amount": 3,
            "unit": "days",
            "reason": "3 kun bog'lanib bo'lmadi",
            **more,
        }

    for bad in (
        new(amount=30, unit="minutes"),
        new(to_column="sold"),
        new(to_column="no_contact"),
        new(from_columns=["discount_20"]),
        new(from_columns=[]),
        new(kind="system"),
        new(unit="weeks"),
        new(name="  "),
    ):
        refused = client.post(path, json=bad, headers=boss)
        assert refused.status_code == 422, bad

    made = client.post(path, json=new(), headers=boss)
    assert made.status_code == 201, made.text
    own = RulesOut.model_validate(made.json()).rules[-1]
    assert own.is_custom and own.kind == "stay" and own.code.startswith("u_")
    assert own.sentence == (
        "Karta «Bog'lanilmadi» ustunida 3 kun tursa → karta «Sovuq»ga o'tadi."
    )

    # Not yet three days there: the card stays.
    assert rules.run_custom(db, board="sales", now=utcnow() + timedelta(days=2)) == 0
    later = utcnow() + timedelta(days=3, minutes=1)
    assert rules.run_custom(db, board="sales", now=later) == 1
    moved = _card(client, seller, card.id)
    assert moved.column == cold
    assert moved.history[0].kind == "rule" and moved.history[0].actor is None
    assert moved.history[0].body == "Uch kun javobsiz. 3 kun bog'lanib bo'lmadi"
    assert (
        moved.why is not None
        and moved.why.auto
        and moved.why.label == "Avtomatik qoida"
    )
    # Once: it is not in the rule's column any more.
    assert rules.run_custom(db, board="sales", now=later + timedelta(days=5)) == 0

    # Changed, switched off, and gone.
    edited = client.patch(
        f"{path}/{own.id}",
        json={**new(amount=5, name="Besh kun"), "is_enabled": False},
        headers=boss,
    )
    assert edited.status_code == 200, edited.text
    last = RulesOut.model_validate(edited.json()).rules[-1]
    assert (last.name, last.amount, last.is_enabled) == ("Besh kun", 5, False)
    held = client.delete(f"{URL}/boards/sales/columns/{cold}", headers=boss)
    assert held.status_code == 422
    gone = client.delete(f"{path}/{own.id}", headers=boss)
    assert gone.status_code == 200 and not any(
        r.is_custom for r in RulesOut.model_validate(gone.json()).rules
    )


def test_a_due_rule_brings_a_ticket_back_from_a_column_of_the_superusers_own(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "ticket@shop.test")
    boss = _staff(db, "boss@office.test", superuser=True)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    raise_ticket(
        db, owner_id=owner.id, reason=TicketReason.SETUP, ref="a", now=utcnow()
    )
    db.commit()
    bank = _custom_column(client, boss, "support", "Bank kutilmoqda")
    made = client.post(
        f"{URL}/boards/support/buttons",
        json={
            "column": "in_progress",
            "action": "go",
            "label": "Bankka yuborildi",
            "to_column": bank,
            "due": "required",
        },
        headers=boss,
    )
    assert made.status_code == 201, made.text
    rule = client.post(
        f"{URL}/boards/support/rules",
        json={
            "kind": "due",
            "name": "Bank muddati",
            "from_columns": [bank],
            "to_column": "in_progress",
            "amount": 0,
            "unit": "minutes",
            "reason": "Bank javobi muddati keldi",
        },
        headers=boss,
    )
    assert rule.status_code == 201, rule.text

    taken = CardDetailOut.model_validate(
        client.post(f"{URL}/support/take", headers=zarina).json()
    )
    own = next(a.value for a in taken.actions if a.value.startswith("b_"))
    due = utcnow() + timedelta(hours=2)
    there = CardDetailOut.model_validate(
        client.post(
            f"{URL}/cards/{taken.id}/actions",
            json={"action": own, "due_at": due.isoformat()},
            headers=zarina,
        ).json()
    )
    assert there.column == bank and there.due_at is not None
    assert triggers.sweep_support(db, now=utcnow()) == 0
    assert (
        db.scalar(select(BoardCard.column_code).where(BoardCard.id == taken.id)) == bank
    )
    triggers.sweep_support(db, now=due + timedelta(minutes=1))
    back = _card(client, zarina, taken.id)
    assert back.column == "in_progress" and back.due_at is None
    assert back.manager is not None
    assert back.history[0].body == "Bank muddati. Bank javobi muddati keldi"


def test_the_migration_seeds_what_the_code_has() -> None:
    """Production gets its rules from migration 0080; a test database from
    the code's own specs. The two must be the same."""
    import importlib.util
    from pathlib import Path

    path = next(
        (Path(__file__).parents[2] / "migrations" / "versions").glob("*_0080_*.py")
    )
    spec = importlib.util.spec_from_file_location("m0080", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = [
        (
            str(s.board),
            s.code,
            list(s.from_columns),
            s.to_column,
            s.amount,
            s.unit,
            s.reason,
        )
        for s in rules.SPECS
    ]
    assert [tuple(seed) for seed in module.SEEDS] == code
