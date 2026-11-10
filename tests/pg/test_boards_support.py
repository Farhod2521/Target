"""The Support board v2 against PostgreSQL: one ticket per client for every
reason, reopened with the same person; setup undone an hour after paying;
Sales' «Support kerak» on payment; Meta's refusals; the buttons."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.audit.models import ActionLog
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import SubscriptionStatus
from app.modules.billing.models import Invoice, Subscription
from app.modules.boards import selectors, triggers
from app.modules.boards.constants import Board, TicketReason
from app.modules.boards.models import BoardCard, BoardCardEvent, BoardSetting
from app.modules.boards.schemas import BoardViewOut, CardDetailOut
from app.modules.boards.tickets import raise_ticket
from app.worker import beat_schedule
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client, _paid, _plan
from tests.pg.test_cabinet_flows import _cabinet

URL = "/api/v2/office"


def _live(db: Session, *, hours_ago: int = 3) -> None:
    for board in Board:
        selectors.ensure_board(db, board=board, now=utcnow())
    db.execute(
        update(BoardSetting).values(live_since=utcnow() - timedelta(hours=hours_ago))
    )
    db.commit()


def _bought(
    db: Session, owner: User, *, minutes_ago: int, setup_done: bool = False
) -> Invoice:
    invoice = _paid(db, owner)
    invoice.paid_at = utcnow() - timedelta(minutes=minutes_ago)
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=_plan(db).id,
            status=SubscriptionStatus.ACTIVE,
            extra_pages=0,
            started_at=invoice.paid_at,
            expires_at=utcnow() + timedelta(days=30),
            setup_completed_at=utcnow() if setup_done else None,
            note="",
        )
    )
    db.commit()
    return invoice


def _ticket(db: Session, owner: User) -> BoardCard | None:
    db.expire_all()
    return db.scalar(
        select(BoardCard).where(
            BoardCard.board == "support", BoardCard.owner_id == owner.id
        )
    )


def _detail(answer: Any) -> CardDetailOut:
    assert answer.status_code == 200, answer.text
    return CardDetailOut.model_validate(answer.json())


def test_setup_undone_an_hour_after_paying_opens_a_ticket(db: Session) -> None:
    _live(db)
    late = _client(db, "late@shop.test")
    fresh = _client(db, "fresh@shop.test")
    ready = _client(db, "ready@shop.test")
    before = _client(db, "before@shop.test")
    _bought(db, late, minutes_ago=61)
    _bought(db, fresh, minutes_ago=30)
    _bought(db, ready, minutes_ago=90, setup_done=True)
    _bought(db, before, minutes_ago=60 * 5)

    assert triggers.sweep_support(db, now=utcnow()) == 1
    ticket = _ticket(db, late)
    assert ticket is not None and ticket.column_code == "new"
    assert [r["code"] for r in ticket.reasons] == ["setup"]
    assert _ticket(db, fresh) is None and _ticket(db, ready) is None
    assert _ticket(db, before) is None

    assert triggers.sweep_support(db, now=utcnow()) == 0


def test_sales_support_kerak_opens_the_ticket_at_payment_not_an_hour_later(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "asks@shop.test")
    triggers.sweep_sales(db, now=utcnow())
    ali = _staff(db, "ali@office.test", Role.SALES)
    card = client.post(f"{URL}/sales/take", headers=ali).json()
    press = f"{URL}/cards/{card['id']}/actions"
    client.post(press, json={"action": "contacted"}, headers=ali)
    client.post(press, json={"action": "needs_support"}, headers=ali)
    assert triggers.sweep_support(db, now=utcnow()) == 0

    _bought(db, owner, minutes_ago=1)
    triggers.sweep_sales(db, now=utcnow())
    assert triggers.sweep_support(db, now=utcnow()) == 1

    ticket = _ticket(db, owner)
    assert ticket is not None and [r["code"] for r in ticket.reasons] == ["from_sales"]

    db.execute(update(Invoice).values(paid_at=utcnow() - timedelta(minutes=61)))
    db.commit()
    assert triggers.sweep_support(db, now=utcnow()) == 1
    ticket = _ticket(db, owner)
    assert ticket is not None
    assert [r["code"] for r in ticket.reasons] == ["from_sales", "setup"]
    assert (
        db.scalar(
            select(func.count())
            .select_from(BoardCard)
            .where(BoardCard.board == "support")
        )
        == 1
    )


def test_meta_refusals_open_a_ticket_and_the_systems_own_do_not(db: Session) -> None:
    _live(db)
    owner = _client(db, "ads@shop.test")
    account, page = _cabinet(db, owner)
    now = utcnow()
    db.add_all(
        [
            CampaignLaunch(
                owner_id=owner.id,
                ad_account_id=account.id,
                page_id=page.id,
                provider=PROVIDER,
                status="failed",
                error_message="Invalid parameter",
                finished_at=now,
            ),
            CampaignLaunch(
                owner_id=owner.id,
                ad_account_id=account.id,
                page_id=page.id,
                provider=PROVIDER,
                status="rolled_back",
                finished_at=now - timedelta(hours=5),
            ),
            CampaignLaunch(
                owner_id=owner.id,
                ad_account_id=account.id,
                page_id=page.id,
                provider=PROVIDER,
                status="created",
                finished_at=now,
            ),
        ]
    )
    for key, actor, code in (
        ("u1", "user", "200"),
        ("u2", "user", "already"),
        ("s1", "system", "200"),
        ("a1", "agent", "200"),
    ):
        db.add(
            ActionLog(
                owner_id=owner.id,
                action="pause",
                target_level="campaign",
                target_external_id="c_1",
                target_provider=PROVIDER,
                idempotency_key=key,
                actor_type=actor,
                status="failed",
                error_code=code,
                error_message="Meta refused",
            )
        )
    db.commit()

    assert triggers.sweep_support(db, now=utcnow()) == 2
    ticket = _ticket(db, owner)
    assert ticket is not None
    assert [r["code"] for r in ticket.reasons] == ["meta_error", "meta_error"]
    details = sorted(r["detail"] for r in ticket.reasons)
    assert details == [
        "Amal bajarilmadi (pause): Meta refused",
        "Reklama ishga tushmadi: Invalid parameter",
    ]
    assert triggers.sweep_support(db, now=utcnow()) == 0


def test_one_ticket_per_client_reopened_with_the_same_person(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "one@shop.test")
    _bought(db, owner, minutes_ago=61)
    triggers.sweep_support(db, now=utcnow())
    ticket = _ticket(db, owner)
    assert ticket is not None
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    olim = _staff(db, "olim@office.test", Role.SUPPORT)
    press = f"{URL}/cards/{ticket.id}/actions"

    seen = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/support", headers=olim).json()
    )
    assert [c.code for c in seen.columns] == ["new", "in_progress", "resolved"]
    assert seen.columns[0].cards[0].reasons == ["setup"]

    started = _detail(client.post(press, json={"action": "start"}, headers=zarina))
    assert started.column == "in_progress" and started.manager is not None
    assert [a.value for a in started.actions] == ["resolve"]
    held = client.post(press, json={"action": "resolve"}, headers=olim)
    assert held.status_code == 409 and held.json()["code"] == "ticket_held"

    solved = _detail(
        client.post(
            press, json={"action": "resolve", "note": "Facebook ulandi"}, headers=zarina
        )
    )
    assert solved.column == "resolved" and solved.actions == []
    assert solved.closed_at is not None

    raise_ticket(
        db,
        owner_id=owner.id,
        reason=TicketReason.META_ERROR,
        ref="launch:x",
        now=utcnow(),
        detail="Xato",
    )
    db.commit()
    again = _detail(client.get(f"{URL}/cards/{ticket.id}", headers=olim))
    assert again.column == "in_progress" and again.closed_at is None
    assert again.manager is not None and again.manager.email == "zarina@office.test"
    assert again.history[0].kind == "reopened"
    assert [r.code for r in again.ticket_reasons] == ["meta_error", "setup"]
    assert db.scalar(select(func.count()).select_from(BoardCard)) == 1


def test_a_new_ticket_nobody_took_reopens_into_yangi(db: Session) -> None:
    _live(db)
    owner = _client(db, "nobody@shop.test")
    now = utcnow()
    raise_ticket(db, owner_id=owner.id, reason=TicketReason.SETUP, ref="a", now=now)
    db.commit()
    ticket = _ticket(db, owner)
    assert ticket is not None
    ticket.column_code = "resolved"
    db.commit()

    assert raise_ticket(
        db, owner_id=owner.id, reason=TicketReason.SETUP, ref="b", now=now
    )
    assert not raise_ticket(
        db, owner_id=owner.id, reason=TicketReason.SETUP, ref="b", now=now
    )
    db.commit()
    ticket = _ticket(db, owner)
    assert ticket is not None and ticket.column_code == "new"
    assert db.scalar(select(func.count()).select_from(BoardCardEvent)) == 2


def test_sales_cannot_open_support_tickets_and_support_cannot_press_sales(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "both@shop.test")
    triggers.sweep_sales(db, now=utcnow())
    raise_ticket(
        db, owner_id=owner.id, reason=TicketReason.SETUP, ref="a", now=utcnow()
    )
    db.commit()
    sales_card = db.scalar(select(BoardCard).where(BoardCard.board == "sales"))
    ticket = _ticket(db, owner)
    assert sales_card is not None and ticket is not None
    ali = _staff(db, "ali@office.test", Role.SALES_LEAD)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)

    assert client.get(f"{URL}/cards/{ticket.id}", headers=ali).status_code == 404
    assert client.get(f"{URL}/cards/{sales_card.id}", headers=zarina).status_code == 404
    wrong = client.post(
        f"{URL}/cards/{ticket.id}/actions", json={"action": "contacted"}, headers=zarina
    )
    assert wrong.status_code == 409


def test_the_superuser_gives_a_ticket_to_support_staff_only(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "give@shop.test")
    raise_ticket(
        db, owner_id=owner.id, reason=TicketReason.SETUP, ref="a", now=utcnow()
    )
    db.commit()
    ticket = _ticket(db, owner)
    assert ticket is not None
    boss = _staff(db, "boss@office.test", superuser=True)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    ali = _staff(db, "ali@office.test", Role.SALES)

    people = client.get(f"{URL}/boards/support/staff", headers=boss).json()["staff"]
    assert [p["email"] for p in people] == ["zarina@office.test"]
    assert client.get(f"{URL}/boards/support/staff", headers=zarina).status_code == 404

    ali_id = db.scalar(select(User.id).where(User.email == "ali@office.test"))
    refused = client.post(
        f"{URL}/cards/{ticket.id}/assign", json={"staff_id": str(ali_id)}, headers=boss
    )
    assert refused.status_code == 422
    given = _detail(
        client.post(
            f"{URL}/cards/{ticket.id}/assign",
            json={"staff_id": people[0]["id"]},
            headers=boss,
        )
    )
    assert given.manager is not None and given.column == "new"
    assert (
        client.post(
            f"{URL}/cards/{ticket.id}/assign", json={"staff_id": None}, headers=zarina
        ).status_code
        == 404
    )
    assert ali  # a sales person is on the team list of Sales only


def test_the_ticket_shows_the_clients_yordam_chat(
    client: TestClient, db: Session
) -> None:
    from app.modules.supportchat.models import SupportConversation

    _live(db)
    owner = _client(db, "chat@shop.test")
    db.add(SupportConversation(owner_id=owner.id))
    raise_ticket(
        db, owner_id=owner.id, reason=TicketReason.SETUP, ref="a", now=utcnow()
    )
    db.commit()
    ticket = _ticket(db, owner)
    assert ticket is not None
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)

    seen = _detail(client.get(f"{URL}/cards/{ticket.id}", headers=zarina))
    assert seen.support_chat_id is not None
    assert seen.ticket_reasons[0].label == "Sozlash tugamadi"


def test_the_support_sweep_is_on_the_beat_every_minute() -> None:
    entries = {e["task"]: e for e in beat_schedule().values()}
    entry = entries["app.modules.boards.tasks.sweep_support_board_task"]
    assert str(entry["schedule"]._orig_minute) == "*"


def test_a_ticket_another_transaction_opened_first_is_used_not_doubled(
    pg_factory: Any, db: Session
) -> None:
    _live(db)
    owner = _client(db, "race@shop.test")
    with pg_factory() as other:
        raise_ticket(
            other, owner_id=owner.id, reason=TicketReason.SETUP, ref="a", now=utcnow()
        )
        other.commit()

    # This session had not seen that card: it tries to open one and meets it.
    assert raise_ticket(
        db, owner_id=owner.id, reason=TicketReason.META_ERROR, ref="b", now=utcnow()
    )
    db.commit()
    ticket = _ticket(db, owner)
    assert ticket is not None
    assert [r["code"] for r in ticket.reasons] == ["setup", "meta_error"]
    assert db.scalar(select(func.count()).select_from(BoardCard)) == 1
