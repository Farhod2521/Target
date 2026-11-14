"""What became of each reason on a Support ticket: «Hal qilindi» solves
every open one together, the client's «Yo'q» opens that round again, a new
reason leaves the old ones solved; and a Meta refusal is said in plain
words, with what it was about."""

import importlib.util
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.models import CampaignLaunch
from app.modules.backoffice.constants import Role
from app.modules.boards import confirm, triggers
from app.modules.boards.constants import TicketReason
from app.modules.boards.models import BoardCard
from app.modules.boards.schemas import BoardViewOut, CardDetailOut
from app.modules.boards.tickets import raise_ticket
from tests.pg.test_boards_help_idle import PROVIDER, _own_cabinet
from tests.pg.test_boards_me import _auth, _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import _live
from tests.pg.test_boards_support_rework import MINE, URL, _detail, _raised


def _board(client: TestClient, head: dict[str, str], **params: Any) -> BoardViewOut:
    answer = client.get(f"{URL}/boards/support", params=params, headers=head)
    assert answer.status_code == 200, answer.text
    return BoardViewOut.model_validate(answer.json())


def _ids(view: BoardViewOut, column: str) -> list[str]:
    return [card.id for card in next(c for c in view.columns if c.code == column).cards]


def _states(card: CardDetailOut) -> list[tuple[str, str]]:
    return [(reason.code, reason.state) for reason in card.ticket_reasons]


def test_hal_qilindi_solves_every_open_reason_and_a_no_opens_them_again(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _raised(db, "shop@shop.test")
    raise_ticket(db, owner_id=owner.id, reason=TicketReason.IDLE, ref="b", now=utcnow())
    db.commit()
    me = _auth(owner)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    press = f"{URL}/cards/{taken.id}/actions"
    assert _states(taken) == [("idle", "open"), ("setup", "open")]
    assert taken.resolution is None and taken.confirm_until is None

    asked = _detail(
        client.post(
            press, json={"action": "resolve", "note": "Ulab berdim"}, headers=zarina
        )
    )
    assert _states(asked) == [("idle", "solved"), ("setup", "solved")]
    assert {r.solved_by for r in asked.ticket_reasons} == {"zarina@office.test"}
    assert {r.solved_note for r in asked.ticket_reasons} == {"Ulab berdim"}
    assert asked.resolution is not None
    assert (asked.resolution.client, asked.resolution.count) == ("waiting", 2)
    assert asked.resolution.note == "Ulab berdim"
    assert asked.confirm_until is not None
    # A solved ticket still says what it was about.
    assert asked.reasons == ["idle", "setup"]

    client.post(f"{MINE}/answer", json={"solved": False}, headers=me)
    back = _detail(client.get(f"{URL}/cards/{taken.id}", headers=zarina))
    assert _states(back) == [("idle", "open"), ("setup", "open")]
    assert all(
        r.denied_at is not None and not r.solved_note for r in back.ticket_reasons
    )
    assert back.client_denied and back.resolution is None
    board = _board(client, zarina)
    card = next(c for c in board.columns if c.code == "in_progress").cards[0]
    assert card.client_denied and not card.client_replied

    client.post(
        press, json={"action": "resolve", "note": "Endi ishladi"}, headers=zarina
    )
    client.post(f"{MINE}/answer", json={"solved": True}, headers=me)
    done = _detail(client.get(f"{URL}/cards/{taken.id}", headers=zarina))
    assert done.column == "resolved" and not done.client_denied
    assert done.resolution is not None and done.resolution.client == "yes"
    assert done.resolution.note == "Endi ishladi"
    assert all(r.denied_at is None for r in done.ticket_reasons)


def test_a_new_reason_leaves_the_old_ones_solved(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _raised(db, "shop@shop.test")
    me = _auth(owner)
    boss = _staff(db, "boss@office.test", superuser=True)
    taken = _detail(client.post(f"{URL}/support/take", headers=boss))
    press = f"{URL}/cards/{taken.id}/actions"
    client.post(press, json={"action": "resolve", "note": "Sozladim"}, headers=boss)
    client.post(f"{MINE}/answer", json={"solved": True}, headers=me)
    assert _ids(_board(client, boss, reason="setup"), "resolved") == [taken.id]

    raise_ticket(
        db,
        owner_id=owner.id,
        reason=TicketReason.META_ERROR,
        ref="launch:x",
        now=utcnow(),
        detail="Reklama ishga tushmadi",
    )
    db.commit()
    again = _detail(client.get(f"{URL}/cards/{taken.id}", headers=boss))
    assert again.column == "in_progress"
    assert _states(again) == [("meta_error", "open"), ("setup", "solved")]
    # The card and the filter read what is open now, not the whole past.
    assert again.reasons == ["meta_error"]
    assert [chip.code for chip in again.reason_chips] == ["meta_error"]
    assert _ids(_board(client, boss, reason="meta_error"), "in_progress") == [taken.id]
    assert _ids(_board(client, boss, reason="setup"), "in_progress") == []

    # Reopened by hand after the next «Hal qilindi»: only that round.
    client.post(
        press, json={"action": "resolve", "note": "Karta qo'shildi"}, headers=boss
    )
    reopened = _detail(client.post(press, json={"action": "reopen"}, headers=boss))
    assert _states(reopened) == [("meta_error", "open"), ("setup", "solved")]
    assert reopened.ticket_reasons[0].denied_at is None


def test_a_meta_refusal_is_said_in_plain_words_with_its_target(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "shop@shop.test")
    account, page = _own_cabinet(db, owner)
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            page_id=page.id,
            provider=PROVIDER,
            status="failed",
            campaign_name="Kuzgi chegirma",
            error_code="payment_missing",
            error_message="Invalid parameter | No Payment Method",
            finished_at=utcnow(),
        )
    )
    db.commit()
    assert triggers.meta_errors(db, now=utcnow()) == 1
    boss = _staff(db, "boss@office.test", superuser=True)
    card = db.scalar(select(BoardCard).where(BoardCard.owner_id == owner.id))
    assert card is not None
    shown = _detail(client.get(f"{URL}/cards/{card.id}", headers=boss))
    reason = shown.ticket_reasons[0]
    assert reason.detail.startswith("«Kuzgi chegirma» reklamasi ishga tushmadi: ")
    assert "Invalid parameter" not in reason.detail
    assert reason.raw == "Invalid parameter | No Payment Method"
    assert reason.target is not None
    assert (reason.target.kind, reason.target.name) == ("launch", "Kuzgi chegirma")
    assert isinstance(shown.client.troubles, list)


def test_silence_leaves_the_round_solved_and_says_so(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _raised(db, "shop@shop.test")
    boss = _staff(db, "boss@office.test", superuser=True)
    taken = _detail(client.post(f"{URL}/support/take", headers=boss))
    client.post(
        f"{URL}/cards/{taken.id}/actions",
        json={"action": "resolve", "note": "Tayyor"},
        headers=boss,
    )
    confirm.close_unanswered(db, now=utcnow() + timedelta(hours=25))
    closed = _detail(client.get(f"{URL}/cards/{taken.id}", headers=boss))
    assert closed.column == "closed"
    assert closed.resolution is not None and closed.resolution.client == "silent"
    assert closed.confirm_until is None


def test_the_migration_reads_the_state_back_from_history() -> None:
    path = next(Path("migrations/versions").glob("*_0055_ticket_reason_state.py"))
    spec = importlib.util.spec_from_file_location("m0055", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def line(
        at: str, kind: str, by: str = "", body: str = "", ref: str = ""
    ) -> dict[str, str]:
        return {"at": at, "kind": kind, "by": by, "body": body, "ref": ref}

    reasons = [
        {"code": "setup", "at": "2026-11-01T10:00:00+00:00"},
        {"code": "idle", "at": "2026-11-03T10:00:00+00:00"},
        {"code": "meta_error", "at": "2026-11-05T10:00:00+00:00"},
    ]
    changed = module.replay(
        reasons,
        [
            line("2026-11-02T10:00:00+00:00", "resolved", "Zarina", "Sozladim"),
            # A new reason reopened it: the first round stays solved.
            line("2026-11-03T10:00:00+00:00", "reopened", "", "", "idle:1"),
            line("2026-11-04T10:00:00+00:00", "resolved", "Zarina", "Yoqdim"),
            line("2026-11-04T12:00:00+00:00", "denied"),
        ],
    )
    assert changed
    assert (
        reasons[0]["solved_note"] == "Sozladim" and reasons[0]["solved_by"] == "Zarina"
    )
    assert "solved_at" not in reasons[1]
    assert reasons[1]["denied_at"] == "2026-11-04T12:00:00+00:00"
    assert "solved_at" not in reasons[2] and "denied_at" not in reasons[2]
    assert (
        module.replay([{"code": "setup", "at": "2026-11-01T10:00:00+00:00"}], [])
        is False
    )
