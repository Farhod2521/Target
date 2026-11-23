"""Support's «Bog'lanib bo'lmadi»: no way to reach the client. The ticket
moves there with a reason from a list the Owner and the superuser keep; it
is not held by the five-ticket limit; the client writing brings it back."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.backoffice.constants import Role
from app.modules.boards import triggers
from app.modules.boards.models import ContactReason
from app.modules.boards.schemas import BoardViewOut, CardDetailOut
from app.modules.supportchat.models import SupportConversation, SupportMessage
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import _live

URL = "/api/v2/office"
REASONS = f"{URL}/boards/support/contact-reasons"


def _detail(answer: Any) -> CardDetailOut:
    assert answer.status_code == 200, answer.text
    return CardDetailOut.model_validate(answer.json())


def _reasons(db: Session) -> tuple[ContactReason, ContactReason]:
    """The two the migration writes; the test database is built from models."""
    wrong = ContactReason(name="Telefon raqam xato", position=1)
    telegram = ContactReason(name="Telegramdan bog'lanib bo'lmadi", position=2)
    db.add_all([wrong, telegram])
    db.commit()
    return wrong, telegram


def _opened(client: TestClient, db: Session, head: dict[str, str]) -> CardDetailOut:
    owner = _client(db, "far@shop.test")
    return _detail_created(
        client.post(
            f"{URL}/boards/support/cards",
            json={"user_id": str(owner.id), "note": "Sozlash"},
            headers=head,
        )
    )


def _detail_created(answer: Any) -> CardDetailOut:
    assert answer.status_code == 201, answer.text
    return CardDetailOut.model_validate(answer.json())


def test_a_ticket_moves_to_unreachable_with_a_reason_and_comes_back(
    client: TestClient, db: Session
) -> None:
    _live(db)
    wrong, _ = _reasons(db)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    opened = _opened(client, db, zarina)
    press = f"{URL}/cards/{opened.id}/actions"
    assert "unreachable" in [a.value for a in opened.actions]

    bare = client.post(press, json={"action": "unreachable"}, headers=zarina)
    assert bare.status_code == 422
    assert bare.json()["detail"] == "Bog'lanib bo'lmaslik sababini tanlang."
    junk = client.post(
        press, json={"action": "unreachable", "reason": "x"}, headers=zarina
    )
    assert junk.status_code == 422

    moved = _detail(
        client.post(
            press,
            json={"action": "unreachable", "reason": str(wrong.id), "note": "2 marta"},
            headers=zarina,
        )
    )
    assert moved.column == "unreachable"
    assert moved.unreachable_reason == "Telefon raqam xato"
    assert [a.value for a in moved.actions] == ["start", "release"]
    assert moved.history[0].kind == "unreachable"
    assert moved.history[0].body == "Telefon raqam xato. 2 marta"

    seen = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/support", headers=zarina).json()
    )
    codes = [c.code for c in seen.columns]
    assert codes.index("unreachable") == codes.index("waiting") + 1
    column = next(c for c in seen.columns if c.code == "unreachable")
    assert column.cards[0].unreachable_reason == "Telefon raqam xato"
    # Not held by the limit: only Ishlanmoqda is.
    assert seen.take is not None and seen.take.working == 0

    # The client writes in the Yordam chat: back to Ishlanmoqda, reason gone.
    owner_id = moved.client.id
    chat = SupportConversation(owner_id=owner_id)
    db.add(chat)
    db.flush()
    db.add(
        SupportMessage(
            owner_id=owner_id,
            conversation_id=chat.id,
            sender_id=owner_id,
            body="Raqamim boshqa",
            created_at=utcnow() + timedelta(seconds=1),
        )
    )
    db.commit()
    assert triggers.sweep_support(db, now=utcnow() + timedelta(seconds=2)) == 1
    back = _detail(client.get(f"{URL}/cards/{opened.id}", headers=zarina))
    assert back.column == "in_progress" and back.unreachable_reason == ""


def test_from_waiting_and_back_by_hand(client: TestClient, db: Session) -> None:
    _live(db)
    _, telegram = _reasons(db)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    opened = _opened(client, db, zarina)
    press = f"{URL}/cards/{opened.id}/actions"
    due = (utcnow() + timedelta(hours=2)).isoformat()
    waiting = _detail(
        client.post(press, json={"action": "wait", "due_at": due}, headers=zarina)
    )
    assert "unreachable" in [a.value for a in waiting.actions]
    moved = _detail(
        client.post(
            press,
            json={"action": "unreachable", "reason": str(telegram.id)},
            headers=zarina,
        )
    )
    # The wait's timer does not carry over.
    assert moved.column == "unreachable" and moved.due_at is None
    started = _detail(client.post(press, json={"action": "start"}, headers=zarina))
    assert started.column == "in_progress" and started.unreachable_reason == ""


def test_the_superuser_keeps_the_list_and_the_owner_reads_it(
    client: TestClient, db: Session
) -> None:
    _live(db)
    wrong, telegram = _reasons(db)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    owner = _staff(db, "owner@office.test", Role.OWNER)
    boss = _staff(db, "boss@office.test", superuser=True)
    sales = _staff(db, "ali@office.test", Role.SALES)

    read = client.get(REASONS, headers=zarina).json()
    assert [r["name"] for r in read["rows"]] == [wrong.name, telegram.name]
    assert read["may_edit"] is False
    assert client.get(REASONS, headers=sales).status_code == 404
    assert client.post(REASONS, json={"name": "X"}, headers=zarina).status_code == 403

    # Since 2026-11-23 every list of reasons is the superuser's alone.
    assert client.post(REASONS, json={"name": "X"}, headers=owner).status_code == 403
    added = client.post(REASONS, json={"name": " Raqam o'chiq "}, headers=boss)
    assert added.status_code == 201, added.text
    assert added.json()["name"] == "Raqam o'chiq" and added.json()["position"] == 3
    by_boss = client.post(REASONS, json={"name": "Boshqa"}, headers=boss)
    assert by_boss.status_code == 201
    renamed = client.put(
        f"{REASONS}/{added.json()['id']}",
        json={"name": "Raqam doim o'chiq", "position": 3},
        headers=boss,
    )
    assert renamed.json()["name"] == "Raqam doim o'chiq"
    assert (
        client.post(f"{REASONS}/{by_boss.json()['id']}/archive", headers=boss).json()[
            "is_archived"
        ]
        is True
    )

    # Support picks from what is live; the Owner and the superuser see the
    # archived too.
    names = [r["name"] for r in client.get(REASONS, headers=zarina).json()["rows"]]
    assert names == [wrong.name, telegram.name, "Raqam doim o'chiq"]
    read_all = client.get(REASONS, headers=owner).json()
    assert read_all["may_edit"] is False and len(read_all["rows"]) == 4
    kept = client.get(REASONS, headers=boss).json()
    assert kept["may_edit"] is True and len(kept["rows"]) == 4

    # An archived reason cannot be picked.
    opened = _opened(client, db, zarina)
    refused = client.post(
        f"{URL}/cards/{opened.id}/actions",
        json={"action": "unreachable", "reason": by_boss.json()["id"]},
        headers=zarina,
    )
    assert refused.status_code == 422
    restored = client.post(f"{REASONS}/{by_boss.json()['id']}/restore", headers=boss)
    assert restored.json()["is_archived"] is False


def test_ko_chirish_into_unreachable_asks_for_a_reason_from_the_list(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _, telegram = _reasons(db)
    boss = _staff(db, "boss@office.test", Role.OWNER)
    opened = _opened(client, db, boss)
    move = f"{URL}/cards/{opened.id}/move"

    bare = client.post(
        move, json={"column": "unreachable", "reason": "Javob yo'q"}, headers=boss
    )
    assert bare.status_code == 422
    assert bare.json()["detail"] == "Bog'lanib bo'lmaslik sababini tanlang."

    moved = _detail(
        client.post(
            move,
            json={
                "column": "unreachable",
                "reason": "Javob yo'q",
                "contact_reason": str(telegram.id),
            },
            headers=boss,
        )
    )
    assert moved.column == "unreachable"
    assert moved.unreachable_reason == "Telegramdan bog'lanib bo'lmadi"
    assert moved.history[0].body == "Telegramdan bog'lanib bo'lmadi. Javob yo'q"

    back = _detail(
        client.post(
            move,
            json={"column": "in_progress", "reason": "Topildi", "contact_reason": "x"},
            headers=boss,
        )
    )
    assert back.column == "in_progress" and back.unreachable_reason == ""
