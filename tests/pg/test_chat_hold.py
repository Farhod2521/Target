"""«Men javob beraman»: one person in Support answers a client in the one
chat, the Owner hands it over, and the assistant answers again when it is
given back or the ticket is done. The office reads the assistant's rows
beside the support chat."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.assistant.models import AssistantMessage, AssistantSession
from app.modules.backoffice.constants import Role
from app.modules.boards.chat_hold import check_writer, hold_of, take_chat
from app.modules.boards.constants import TICKET_TAKE_LIMIT, SupportColumn
from app.modules.boards.exceptions import ChatHeld, ChatNotTaken, TakeLimit
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.supportchat.models import SupportConversation, SupportMessage
from tests.pg.test_office_actions import _staff
from tests.pg.test_supportchat import _send, _user

URL = "/api/v1/office/support"
BOARDS = "/api/v2/office"


def _take(client: TestClient, owner_id: object, headers: dict[str, str]):  # type: ignore[no-untyped-def]
    return client.post(f"{URL}/customers/{owner_id}/chat/take", headers=headers)


def _hold(db: Session, owner_id: object):  # type: ignore[no-untyped-def]
    db.expire_all()
    return hold_of(db, owner_id=owner_id)  # type: ignore[arg-type]


def _card(db: Session, owner_id: object) -> BoardCard:
    db.expire_all()
    card = db.scalar(select(BoardCard).where(BoardCard.owner_id == owner_id))
    assert card is not None
    return card


def test_one_person_at_a_time_and_the_owner_hands_it_over(
    client: TestClient, db: Session
) -> None:
    owner = _user(db, "mijoz@example.com")
    aziz, aziz_h = _staff(db, Role.SUPPORT, email="aziz@office.test")
    olim, olim_h = _staff(db, Role.SUPPORT, email="olim@office.test")
    boss, boss_h = _staff(db, Role.OWNER, email="boss@office.test")
    seller, _ = _staff(db, Role.SALES, email="seller@office.test")
    _send(client, owner, body="Reklama to'xtadi")

    # No ticket yet: taking opens one, given to whoever took it.
    taken = _take(client, owner.id, aziz_h)
    assert taken.status_code == 200, taken.text
    assert taken.json()["mine"] is True and taken.json()["can_release"] is True
    card = _card(db, owner.id)
    assert card.manager_id == aziz.id
    assert card.column_code == SupportColumn.IN_PROGRESS
    assert card.reasons[-1]["code"] == "manual"
    assert _take(client, owner.id, aziz_h).status_code == 200  # again: nothing

    # Olim sees who has it and can neither take it nor write.
    seen = client.get(f"{URL}/customers/{owner.id}", headers=olim_h).json()["chat"]
    assert seen["holder"]["id"] == str(aziz.id)
    assert seen["can_take"] is False and seen["can_release"] is False
    assert seen["busy_with"] == "aziz@office.test"
    refused = _take(client, owner.id, olim_h)
    assert refused.status_code == 409 and "aziz@office.test" in refused.json()["detail"]
    chat = db.scalar(select(SupportConversation))
    assert chat is not None
    wrote = client.post(f"{URL}/{chat.id}/messages", headers=olim_h, data={"body": "x"})
    assert wrote.status_code == 409
    assert wrote.json()["code"] == "chat_held"
    assert (
        client.post(
            f"{URL}/customers/{owner.id}/chat/release", headers=olim_h
        ).status_code
        == 409
    )
    # Only the Owner hands it over.
    handed = client.post(
        f"{URL}/customers/{owner.id}/chat/hand",
        headers=aziz_h,
        json={"staff_id": str(olim.id)},
    )
    assert handed.status_code == 404

    # The Owner gives it to Olim: the ticket goes with it.
    owner_view = client.get(f"{URL}/customers/{owner.id}", headers=boss_h).json()
    assert owner_view["chat"]["can_take"] and owner_view["chat"]["can_hand"]
    assert owner_view["chat"]["busy_with"] == ""
    handed = client.post(
        f"{URL}/customers/{owner.id}/chat/hand",
        headers=boss_h,
        json={"staff_id": str(olim.id)},
    )
    assert handed.status_code == 200, handed.text
    assert handed.json()["holder"]["id"] == str(olim.id)
    assert _card(db, owner.id).manager_id == olim.id
    # Not to somebody outside Support.
    wrong = client.post(
        f"{URL}/customers/{owner.id}/chat/hand",
        headers=boss_h,
        json={"staff_id": str(seller.id)},
    )
    assert wrong.status_code == 422
    # Olim writes now; Aziz may not.
    ok = client.post(f"{URL}/{chat.id}/messages", headers=olim_h, data={"body": "Ha"})
    assert ok.status_code == 201, ok.text
    no = client.post(f"{URL}/{chat.id}/messages", headers=aziz_h, data={"body": "x"})
    assert no.status_code == 409

    # The Owner takes it for themselves, then gives it back to the assistant.
    assert _take(client, owner.id, boss_h).json()["mine"] is True
    assert _card(db, owner.id).manager_id == boss.id
    back = client.post(f"{URL}/customers/{owner.id}/chat/release", headers=boss_h)
    assert back.json()["holder"] is None
    assert _hold(db, owner.id) is None
    # The ticket stays the Owner's; only the chat went back.
    assert _card(db, owner.id).manager_id == boss.id
    # Nobody has the chat, but the ticket is somebody else's: not Aziz's.
    other = _take(client, owner.id, aziz_h)
    assert other.status_code == 409 and other.json()["code"] == "chat_held"
    assert "zayavkasi boss@office.test da" in other.json()["detail"]

    kinds = list(
        db.scalars(
            select(BoardCardEvent.kind)
            .where(BoardCardEvent.card_id == card.id)
            .order_by(BoardCardEvent.created_at)
        )
    )
    assert "chat_taken" in kinds and "chat_handed" in kinds
    assert kinds[-1] == "chat_released"


def test_the_ticket_given_back_or_done_returns_the_chat(
    client: TestClient, db: Session
) -> None:
    owner = _user(db, "mijoz@example.com")
    aziz, aziz_h = _staff(db, Role.SUPPORT, email="aziz@office.test")
    _boss, boss_h = _staff(db, Role.OWNER, email="boss@office.test")
    _send(client, owner, body="Savol")
    _take(client, owner.id, aziz_h)
    card = _card(db, owner.id)

    # The Owner takes the ticket back to Yangi: nobody has the chat.
    back = client.post(
        f"{BOARDS}/cards/{card.id}/assign", headers=boss_h, json={"staff_id": None}
    )
    assert back.status_code == 200, back.text
    assert _card(db, owner.id).chat_taken_at is None
    assert _hold(db, owner.id) is None

    # Taken again; «Hal qilindi» gives it back to the assistant.
    _take(client, owner.id, aziz_h)
    assert _hold(db, owner.id) is not None
    solved = client.post(
        f"{BOARDS}/cards/{card.id}/actions",
        headers=aziz_h,
        json={"action": "resolve", "note": "Tuzatildi"},
    )
    assert solved.status_code == 200, solved.text
    assert _card(db, owner.id).column_code == SupportColumn.CONFIRMING
    assert _hold(db, owner.id) is None

    # A solved ticket is reopened by the next take, with the same person.
    again = _take(client, owner.id, aziz_h)
    assert again.status_code == 200, again.text
    reopened = _card(db, owner.id)
    assert reopened.column_code == SupportColumn.IN_PROGRESS
    assert reopened.manager_id == aziz.id


def test_a_free_ticket_counts_against_the_take_limit(db: Session) -> None:
    aziz, _ = _staff(db, Role.SUPPORT, email="aziz@office.test")
    now = utcnow()
    for n in range(TICKET_TAKE_LIMIT):
        client_n = _user(db, f"band{n}@example.com")
        take_chat(db, client=client_n, user=aziz, now=now)
        db.commit()
    one_more = _user(db, "oxirgi@example.com")
    with pytest.raises(TakeLimit):
        take_chat(db, client=one_more, user=aziz, now=now)
    db.rollback()


def test_a_reply_from_telegram_takes_a_free_chat_only(db: Session) -> None:
    owner = _user(db, "mijoz@example.com")
    aziz, _ = _staff(db, Role.SUPPORT, email="aziz@office.test")
    olim, _ = _staff(db, Role.SUPPORT, email="olim@office.test")
    now = utcnow()
    with pytest.raises(ChatNotTaken):
        check_writer(db, owner_id=owner.id, sender=aziz, now=now)
    check_writer(db, owner_id=owner.id, sender=aziz, now=now, take=True)
    db.commit()
    hold = hold_of(db, owner_id=owner.id)
    assert hold is not None and hold.holder.id == aziz.id
    with pytest.raises(ChatHeld):
        check_writer(db, owner_id=owner.id, sender=olim, now=now, take=True)


def test_the_office_reads_the_assistants_rows_beside_the_support_chat(
    client: TestClient, db: Session
) -> None:
    owner = _user(db, "mijoz@example.com")
    aziz, aziz_h = _staff(db, Role.SUPPORT, email="aziz@office.test")
    then = utcnow() - timedelta(hours=1)
    old = AssistantSession(owner_id=owner.id, title="Reklama", last_message_at=then)
    new = AssistantSession(
        owner_id=owner.id, title="To'lov", last_message_at=then + timedelta(minutes=30)
    )
    db.add_all([old, new])
    db.flush()
    db.add_all(
        [
            AssistantMessage(
                owner_id=owner.id,
                session_id=old.id,
                author="user",
                text="Nega to'xtadi?",
                created_at=then,
            ),
            AssistantMessage(
                owner_id=owner.id,
                session_id=old.id,
                author="ai",
                text="Kartangiz rad etilgan.",
                buttons=[
                    {
                        "kind": "ticket",
                        "key": "t1",
                        "label": "Mutaxassisga yuborish",
                        "state": "sent",
                        "summary": "Karta rad etildi",
                    }
                ],
                created_at=then + timedelta(minutes=1),
            ),
            AssistantMessage(
                owner_id=owner.id,
                session_id=new.id,
                author="ai",
                text="",
                status="failed",
                created_at=then + timedelta(minutes=30),
            ),
        ]
    )
    db.commit()

    screen = client.get(f"{URL}/customers/{owner.id}", headers=aziz_h).json()
    rows = screen["assistant"]
    assert [(r["author"], r["thread_title"]) for r in rows] == [
        ("user", "Reklama"),
        ("ai", "Reklama"),
        ("ai", "To'lov"),
    ]
    assert rows[1]["offered"] == [
        {
            "kind": "ticket",
            "label": "Mutaxassisga yuborish",
            "summary": "Karta rad etildi",
            "state": "sent",
        }
    ]
    assert rows[2]["status"] == "failed"

    # Taken, the person's words go to the thread the client wrote in last,
    # and that row is the support chat's: the office does not list it twice.
    _take(client, owner.id, aziz_h)
    db.expire_all()
    assert db.get(AssistantSession, new.id).support_at is not None  # type: ignore[union-attr]
    sent = client.post(
        f"{URL}/customers/{owner.id}/messages", headers=aziz_h, data={"body": "Salom"}
    )
    assert sent.status_code == 201, sent.text
    message = db.scalar(select(SupportMessage))
    assert message is not None
    row = db.scalar(
        select(AssistantMessage).where(
            AssistantMessage.support_message_id == message.id
        )
    )
    assert row is not None and row.session_id == new.id
    screen = client.get(f"{URL}/customers/{owner.id}", headers=aziz_h).json()
    assert len(screen["assistant"]) == 3
    assert [m["body"] for m in screen["messages"]] == ["Salom"]
    assert aziz  # the sender is the person who took it
