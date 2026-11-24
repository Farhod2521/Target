"""What the superuser's own rules read and do besides moving a card (how
many calls did not reach, the client's plan, their bill, a word to Yordam;
a time, a Telegram word, another person), a rule tried before it is kept,
the journal of the settings, and the board column by column."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.boards import rules
from app.modules.boards.constants import Board
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.schemas import (
    ColumnsReportOut,
    RulePreviewOut,
    RulesOut,
    SettingsHistoryOut,
)
from tests.pg.test_boards_deadlines import _bill
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_rules import _card, _custom_column, _lead
from tests.pg.test_sales_board_fixes import _Bot, _chat

URL = "/api/v2/office"
RULES = f"{URL}/boards/sales/rules"


def _body(**over: Any) -> dict[str, Any]:
    return {
        "kind": "stay",
        "name": "Uch marta javob bermadi",
        "from_columns": ["no_contact"],
        "to_column": "",
        "amount": 1,
        "unit": "hours",
        "reason": "",
        **over,
    }


def _added(client: TestClient, head: dict[str, str], **over: Any) -> RulesOut:
    answer = client.post(RULES, json=_body(**over), headers=head)
    assert answer.status_code == 201, answer.text
    return RulesOut.model_validate(answer.json())


def _place(
    db: Session, card_id: str, column: str, *, hours: float, **more: Any
) -> None:
    db.execute(
        update(BoardCard)
        .where(BoardCard.id == card_id)
        .values(
            column_code=column,
            column_since=utcnow() - timedelta(hours=hours),
            **more,
        )
    )
    db.commit()


def _run(db: Session, bot: _Bot | None = None) -> int:
    return rules.run_custom(db, board=Board.SALES, now=utcnow(), client=bot)


def test_a_rule_reads_the_missed_calls_and_sets_a_time_once(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    card, _ = _lead(client, db, seller)
    view = _added(
        client,
        boss,
        attempts_min=3,
        due_amount=0,
        due_unit="minutes",
        reason="Uch marta qo'ng'iroq qilindi",
    )
    own = next(rule for rule in view.rules if rule.is_custom)
    assert own.attempts_min == 3 and own.due_amount == 0 and own.to_column == ""
    assert "3 marta bog'lanib bo'lmagan" in own.sentence
    assert "muddati «hozir» bo'ladi" in own.sentence

    # Two calls missed: not yet.
    _place(db, card.id, "no_contact", hours=2, attempts=2)
    assert _run(db) == 0
    _place(db, card.id, "no_contact", hours=2, attempts=3)
    assert _run(db) == 1
    seen = _card(client, seller, card.id)
    assert seen.column == "no_contact" and seen.due_at is not None
    assert seen.history[0].kind == "rule"
    assert "Uch marta qo'ng'iroq qilindi" in seen.history[0].body
    # The card stayed where it was: the rule does not fire on it again.
    assert _run(db) == 0


def test_a_rule_needs_something_to_do_and_a_board_that_counts_calls(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    for body in (
        _body(),
        _body(to_column="callback", plans=["nothing"]),
        _body(to_column="callback", bill="later"),
        _body(to_column="callback", assign_to="not-a-person"),
        _body(due_amount=1, due_unit="weeks"),
        _body(kind="often", to_column="callback"),
    ):
        refused = client.post(RULES, json=body, headers=boss)
        assert refused.status_code == 422, body
        assert refused.json()["code"] == "rule_invalid", body
    support = client.post(
        f"{URL}/boards/support/rules",
        json=_body(from_columns=["waiting"], to_column="in_progress", attempts_min=2),
        headers=boss,
    )
    assert support.status_code == 422, support.text


def test_a_rule_reads_the_plan_and_the_bill(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    billed, owner = _lead(client, db, seller)
    plain, _ = _lead(client, db, seller)
    _added(
        client,
        boss,
        name="Hisob ochgan",
        from_columns=["contacted"],
        to_column="callback",
        plans=["none"],
        bill="open",
    )
    for card in (billed, plain):
        _place(db, card.id, "contacted", hours=2)
    _bill(db, owner)

    tried = client.post(
        f"{RULES}/preview",
        json=_body(
            name="Hisob ochgan",
            from_columns=["contacted"],
            to_column="callback",
            plans=["none"],
            bill="open",
        ),
        headers=boss,
    )
    assert tried.status_code == 200, tried.text
    found = RulePreviewOut.model_validate(tried.json())
    assert found.count == 1 and found.cards[0].id == str(billed.id)
    # A trial changes nothing.
    assert _card(client, seller, billed.id).column == "contacted"

    assert _run(db) == 1
    assert _card(client, seller, billed.id).column == "callback"
    assert _card(client, seller, plain.id).column == "contacted"


def test_a_rule_tells_on_telegram_and_gives_the_card_to_another(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    _staff(db, "vali@office.test", Role.SALES)
    _staff(db, "lead@office.test", Role.SALES_LEAD)
    for email, chat in (
        ("ali@office.test", "501"),
        ("vali@office.test", "502"),
        ("lead@office.test", "503"),
    ):
        _chat(db, email, chat)
    vali = db.scalar(select(User).where(User.email == "vali@office.test"))
    assert vali is not None
    card, _ = _lead(client, db, seller)
    view = _added(
        client,
        boss,
        name="Uzoq turdi",
        from_columns=["callback"],
        notify_manager=True,
        notify_lead=True,
        notify_text="Shu mijozga qo'ng'iroq qiling",
        assign_to=str(vali.id),
    )
    own = next(rule for rule in view.rules if rule.is_custom)
    assert "Telegram xabar" in own.sentence and own.assign_to == str(vali.id)
    assert {choice.value for choice in view.staff} >= {str(vali.id)}

    _place(db, card.id, "callback", hours=3)
    bot = _Bot()
    assert _run(db, bot) == 1
    # The card's new person and the lead hear; the one it left does not.
    assert {chat for chat, _ in bot.sent} == {"502", "503"}
    assert "Shu mijozga qo'ng'iroq qiling" in bot.sent[0][1]
    assert "Uzoq turdi" in bot.sent[0][1]
    kept = db.get(BoardCard, card.id)
    assert kept is not None
    db.refresh(kept)
    assert kept.manager_id == vali.id and kept.column_code == "callback"
    assert _run(db, bot) == 0 and len(bot.sent) == 2


def test_a_rule_fires_when_the_client_writes_to_yordam(
    client: TestClient, db: Session
) -> None:
    from app.modules.supportchat.models import SupportConversation, SupportMessage

    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    card, owner = _lead(client, db, seller)
    _added(
        client,
        boss,
        kind="wrote",
        name="Mijoz yozdi",
        from_columns=["no_contact"],
        to_column="callback",
        amount=0,
    )
    _place(db, card.id, "no_contact", hours=1)
    assert _run(db) == 0
    chat = SupportConversation(owner_id=owner.id)
    db.add(chat)
    db.flush()
    db.add(
        SupportMessage(
            owner_id=owner.id,
            conversation_id=chat.id,
            sender_id=owner.id,
            body="Salom",
        )
    )
    db.commit()
    assert _run(db) == 1
    assert _card(client, seller, card.id).column == "callback"


def test_the_settings_keep_who_changed_what(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    owner = _staff(db, "owner@office.test", Role.OWNER)
    seller = _staff(db, "ali@office.test", Role.SALES)
    path = f"{URL}/boards/sales/settings/history"
    code = _custom_column(client, boss, "sales", "O'ylab ko'radi")
    client.put(
        f"{URL}/boards/sales/columns/{code}/talked", json={"talked": True}, headers=boss
    )
    view = _added(client, boss, to_column=code, name="Uzoq turdi")
    own = next(rule for rule in view.rules if rule.is_custom)
    sold = next(rule for rule in view.rules if rule.code == "sales.sold")
    client.patch(f"{RULES}/{sold.id}", json={"reason": "Pul tushdi"}, headers=boss)
    client.patch(
        f"{RULES}/{own.id}",
        json={**_body(to_column=code, name="Uzoq turdi"), "is_enabled": False},
        headers=boss,
    )
    # A refused write keeps nothing.
    assert (
        client.patch(f"{RULES}/{sold.id}", json={"amount": 5}, headers=boss).status_code
        == 422
    )
    client.delete(f"{RULES}/{own.id}", headers=boss)

    answer = client.get(path, headers=owner)
    assert answer.status_code == 200, answer.text
    rows = SettingsHistoryOut.model_validate(answer.json()).rows
    told = [(row.area, row.action, row.name) for row in reversed(rows)]
    assert told == [
        ("column", "add", "O'ylab ko'radi"),
        ("column", "edit", "O'ylab ko'radi"),
        ("rule", "add", "Uzoq turdi"),
        ("rule", "edit", "Sotildi"),
        ("rule", "edit", "Uzoq turdi"),
        ("rule", "remove", "Uzoq turdi"),
    ]
    by_name = {(row.area, row.action, row.name): row for row in rows}
    assert (
        "Gaplashilgan: yo'q → ha" in by_name[("column", "edit", "O'ylab ko'radi")].body
    )
    assert "«Pul tushdi»" in by_name[("rule", "edit", "Sotildi")].body
    assert "Yoqilgan: ha → yo'q" in by_name[("rule", "edit", "Uzoq turdi")].body
    assert all(row.actor == "boss@office.test" for row in rows)

    only = SettingsHistoryOut.model_validate(
        client.get(path, params={"area": "column"}, headers=owner).json()
    )
    assert {row.area for row in only.rows} == {"column"}
    assert client.get(path, headers=seller).status_code == 404


def test_the_board_is_read_column_by_column(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    other = _staff(db, "vali@office.test", Role.SALES)
    code = _custom_column(client, boss, "sales", "O'ylab ko'radi")
    card, _ = _lead(client, db, seller)
    theirs, _ = _lead(client, db, other)
    for one in (card, theirs):
        moved = client.post(
            f"{URL}/cards/{one.id}/move",
            json={"column": code, "reason": "O'ylab ko'rmoqchi"},
            headers=boss,
        )
        assert moved.status_code == 200, moved.text
    # The card stood there two hours, then went on.
    db.execute(
        update(BoardCardEvent)
        .where(BoardCardEvent.card_id == card.id, BoardCardEvent.to_column == code)
        .values(created_at=utcnow() - timedelta(hours=2))
    )
    db.commit()
    client.post(
        f"{URL}/cards/{card.id}/move",
        json={"column": "callback", "reason": "Qayta gaplashamiz"},
        headers=boss,
    )

    def read(head: dict[str, str]) -> dict[str, Any]:
        answer = client.get(f"{URL}/boards/sales/columns/report", headers=head)
        assert answer.status_code == 200, answer.text
        body = ColumnsReportOut.model_validate(answer.json())
        return {row.code: row for row in body.rows} | {"everybody": body.everybody}

    whole = read(boss)
    assert whole["everybody"] is True
    assert whole[code].is_custom and whole[code].name == "O'ylab ko'radi"
    assert (whole[code].now, whole[code].entered, whole[code].left) == (1, 2, 1)
    assert whole[code].stay_hours == 2.0
    assert whole["callback"].now == 1 and whole["callback"].entered == 1
    # A manager reads their own cards only.
    mine = read(seller)
    assert mine["everybody"] is False
    assert (mine[code].now, mine[code].entered) == (0, 1)
    assert mine["callback"].now == 1


def test_the_migration_marks_the_columns_the_code_counts_as_talked() -> None:
    import importlib

    from app.modules.boards.constants import START_TALKED_COLUMNS

    migration = importlib.import_module(
        "migrations.versions.20261124_0081_board_automation"
    )
    assert set(migration.TALKED) == set(START_TALKED_COLUMNS)
