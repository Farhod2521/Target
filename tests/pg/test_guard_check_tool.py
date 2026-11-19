"""``tools.guard_check``: the half-hourly guard for one email, run by hand."""

from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.pg.test_guard import _linked_phone, _pauses, _rows, _running, _today


def _tool(db: Session, monkeypatch, phone=None):
    import tools.guard_check as tool
    from app.modules.notifications import bot as bot_module

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(tool, "task_session", session)
    if phone is not None:

        @contextmanager
        def opened():
            yield phone

        monkeypatch.setattr(bot_module, "bot", opened)
        monkeypatch.setattr(bot_module, "is_configured", lambda: True)
    return tool


def test_an_unknown_email_is_said(
    client: TestClient, db: Session, monkeypatch, capsys
) -> None:
    tool = _tool(db, monkeypatch)
    assert tool.main(["nobody@example.com"]) == 1
    assert "bunday foydalanuvchi yo'q" in capsys.readouterr().out


def test_look_writes_nothing(
    client: TestClient, db: Session, queued: list, monkeypatch, capsys
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=3_060, leads=3)
    tool = _tool(db, monkeypatch)

    assert tool.main([owner.email.upper(), "--look", "--no-sync"]) == 0
    out = capsys.readouterr().out
    assert "-> price: warn, bosqich 5, 5.1x" in out
    assert "[juftlikda]" in out
    assert _rows(db) == [] and _pauses(db) == []


def test_the_pass_writes_stops_and_tells_the_phone(
    client: TestClient, db: Session, queued: list, monkeypatch, capsys
) -> None:
    owner, account, now = _running(client, db)
    phone = _linked_phone(db, owner, now, monkeypatch)
    _today(db, owner, account, now, spend=3_060, leads=3)
    tool = _tool(db, monkeypatch, phone=phone)

    assert tool.main([owner.email, "--no-sync", "--ignore-night"]) == 0
    out = capsys.readouterr().out
    assert "Guard: 1 ta topilma" in out
    assert "yuborildi: 1" in out
    (row,) = _rows(db)
    assert (row.kind, row.step, row.said_step) == ("price", 5, 5)
    assert len(phone.texts()) == 1


def test_no_stop_only_warns(
    client: TestClient, db: Session, queued: list, monkeypatch, capsys
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=6_060, leads=3)
    tool = _tool(db, monkeypatch)

    assert tool.main([owner.email, "--no-sync", "--no-stop", "--no-telegram"]) == 0
    (row,) = _rows(db)
    assert row.action == "warn"
    assert _pauses(db) == []
