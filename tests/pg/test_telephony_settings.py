"""The office's telephony settings against PostgreSQL: signing in to UTeL,
the internal numbers and who answers each, the events address, and what
UTeL sends to it. UTeL itself is a fake here."""

from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import crypto
from app.common.config import settings
from app.common.deletion import delete_rows
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.boards.schemas import MeOut
from app.modules.telephony import utel
from app.modules.telephony.constants import HOOK_EVENTS
from app.modules.telephony.models import PhoneConnection, PhoneExtension, PhoneHookEvent
from app.modules.telephony.schemas import TelephonyOut
from tests.pg.test_boards_me import _staff

URL = "/api/v2/office/telephony"
LOGIN = {
    "tenant": "https://UTC181.utel.uz/",
    "email": "api@firma.uz",
    "password": "sir",
}
OTHER_HOOK = {"url": "https://boshqa.example/hook"} | dict.fromkeys(HOOK_EVENTS, False)


class Exchange:
    """UTeL as the settings see it."""

    def __init__(self) -> None:
        self.password = "sir"
        self.token = "1|kalit"
        self.numbers = [("101", "Operator 1", "p101"), ("102", "Operator 2", "p102")]
        self.hook_rows: list[dict[str, Any]] = [dict(OTHER_HOOK)]
        self.down = False
        self.hooks_down = False
        self.tenants: list[str] = []

    def login(self, tenant: str, *, email: str, password: str) -> str:
        self.tenants.append(tenant)
        if self.down:
            raise utel.Unreachable
        if password != self.password:
            raise utel.Refused
        return self.token

    def _key(self, token: str) -> None:
        if self.down:
            raise utel.Unreachable
        if token != self.token:
            raise utel.Refused

    def extensions(self, tenant: str, *, token: str) -> list[utel.Extension]:
        self._key(token)
        return [utel.Extension(*row) for row in self.numbers]

    def hooks(self, tenant: str, *, token: str) -> list[dict[str, Any]]:
        self._key(token)
        if self.hooks_down:
            raise utel.Unreachable
        return [dict(row) for row in self.hook_rows]

    def put_hooks(self, tenant: str, *, token: str, rows: list[dict[str, Any]]) -> None:
        self._key(token)
        self.hook_rows = [dict(row) for row in rows]


@pytest.fixture
def exchange(monkeypatch: pytest.MonkeyPatch) -> Exchange:
    fake = Exchange()
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    for name in ("login", "extensions", "hooks", "put_hooks"):
        monkeypatch.setattr(utel, name, getattr(fake, name))
    return fake


def _state(answer: Any) -> TelephonyOut:
    assert answer.status_code == 200, answer.text
    return TelephonyOut.model_validate(answer.json())


def _ours(exchange: Exchange) -> list[dict[str, Any]]:
    return [row for row in exchange.hook_rows if "/webhooks/utel/" in row["url"]]


def test_only_the_superuser_and_the_owner_open_the_settings(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    owner = _staff(db, "ega@office.test", Role.OWNER)
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)

    assert client.get(URL, headers=lead).status_code == 404
    assert client.put(f"{URL}/connection", json=LOGIN, headers=lead).status_code == 404
    assert client.get(URL).status_code == 401
    assert not _state(client.get(URL, headers=owner)).connected
    empty = _state(client.get(URL, headers=boss))
    assert empty.connection is None and empty.extensions == []
    assert {person.email for person in empty.staff} == {
        "boss@office.test",
        "ega@office.test",
        "rahbar@office.test",
    }
    me = MeOut.model_validate(client.get("/api/v2/office/me", headers=boss).json())
    assert me.can.telephony
    me = MeOut.model_validate(client.get("/api/v2/office/me", headers=lead).json())
    assert not me.can.telephony


def test_signing_in_reads_the_numbers_and_asks_for_events(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)

    answer = client.put(f"{URL}/connection", json=LOGIN, headers=boss)
    state = _state(answer)

    assert exchange.tenants == ["utc181"]
    assert state.connected and state.connection is not None
    assert state.connection.tenant == "utc181"
    assert state.connection.sip_domain == "utc181.utel.uz"
    assert state.connection.sip_socket == "wss://utc181.utel.uz:8089/ws"
    assert state.connection.hook_set_at is not None
    assert state.connection.last_error == ""
    assert [(row.number, row.title) for row in state.extensions] == [
        ("101", "Operator 1"),
        ("102", "Operator 2"),
    ]
    # The other system's address is still on UTeL's list, untouched.
    assert exchange.hook_rows[0] == OTHER_HOOK
    (ours,) = _ours(exchange)
    assert all(ours[event] is True for event in HOOK_EVENTS)

    row = db.scalar(select(PhoneConnection))
    assert row is not None and row.owner_id is None
    assert ours["url"] == f"{settings.site_url}/webhooks/utel/{row.hook_key}"
    assert crypto.decrypt(row.api_token) == "1|kalit"
    kept = db.scalar(select(PhoneExtension).where(PhoneExtension.number == "101"))
    assert kept is not None and crypto.decrypt(kept.sip_password) == "p101"
    # Nothing secret in the answer.
    for secret in ("1|kalit", "p101", row.hook_key, "sir"):
        assert secret not in answer.text


def test_a_wrong_login_or_a_strange_address_ties_nothing(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)

    wrong = client.put(
        f"{URL}/connection", json=LOGIN | {"password": "xato"}, headers=boss
    )
    assert wrong.status_code == 422
    assert wrong.json()["code"] == "exchange_refused_login"
    for address in ("evil.example.com", "utc181.utel.uz.evil.com", "a b", "utc@x"):
        strange = client.put(
            f"{URL}/connection", json=LOGIN | {"tenant": address}, headers=boss
        )
        assert strange.status_code == 422, address
        assert strange.json()["code"] == "tenant_shape"
    exchange.down = True
    silent = client.put(f"{URL}/connection", json=LOGIN, headers=boss)
    assert silent.status_code == 502
    assert silent.json()["code"] == "exchange_unreachable"

    assert exchange.tenants == ["utc181", "utc181"]
    assert db.scalar(select(func.count()).select_from(PhoneConnection)) == 0
    assert client.post(f"{URL}/sync", headers=boss).json()["code"] == "not_connected"


def test_events_not_asked_for_keeps_the_connection_and_says_so(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    exchange.hooks_down = True

    state = _state(client.put(f"{URL}/connection", json=LOGIN, headers=boss))

    assert state.connection is not None and state.connection.hook_set_at is None
    assert state.connection.last_error
    assert len(state.extensions) == 2 and _ours(exchange) == []

    exchange.hooks_down = False
    again = _state(client.post(f"{URL}/hook", headers=boss))
    assert again.connection is not None and again.connection.hook_set_at is not None
    assert again.connection.last_error == ""
    # Asked twice, our address is there once.
    client.post(f"{URL}/hook", headers=boss)
    assert len(_ours(exchange)) == 1 and len(exchange.hook_rows) == 2


def test_a_number_is_given_moved_and_taken_back(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    _staff(db, "sotuv@office.test", Role.SALES)
    seller = db.scalar(select(User).where(User.email == "sotuv@office.test"))
    client_user = User(email="mijoz@example.com", full_name="Mijoz", password="!")
    db.add(client_user)
    db.commit()
    assert seller is not None
    state = _state(client.put(f"{URL}/connection", json=LOGIN, headers=boss))
    first, second = state.extensions

    given = _state(
        client.patch(
            f"{URL}/extensions/{first.id}",
            json={"user_id": str(seller.id)},
            headers=boss,
        )
    )
    assert given.extensions[0].user is not None
    assert given.extensions[0].user.email == "sotuv@office.test"
    assert given.extensions[0].softphone

    # A person holds one number: given the second, they leave the first.
    moved = _state(
        client.patch(
            f"{URL}/extensions/{second.id}",
            json={"user_id": str(seller.id), "softphone": False},
            headers=boss,
        )
    )
    assert moved.extensions[0].user is None
    assert moved.extensions[1].user is not None and not moved.extensions[1].softphone

    # The browser phone alone: who answers stays.
    on = _state(
        client.patch(
            f"{URL}/extensions/{second.id}", json={"softphone": True}, headers=boss
        )
    )
    assert on.extensions[1].user is not None and on.extensions[1].softphone

    stranger = client.patch(
        f"{URL}/extensions/{first.id}",
        json={"user_id": str(client_user.id)},
        headers=boss,
    )
    assert stranger.status_code == 422 and stranger.json()["code"] == "not_staff"

    back = _state(
        client.patch(
            f"{URL}/extensions/{second.id}", json={"user_id": None}, headers=boss
        )
    )
    assert back.extensions[1].user is None


def test_a_number_utel_dropped_is_marked_gone_and_freed(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    _staff(db, "sotuv@office.test", Role.SALES)
    seller = db.scalar(select(User).where(User.email == "sotuv@office.test"))
    assert seller is not None
    state = _state(client.put(f"{URL}/connection", json=LOGIN, headers=boss))
    gone_id = state.extensions[1].id
    client.patch(
        f"{URL}/extensions/{gone_id}", json={"user_id": str(seller.id)}, headers=boss
    )
    exchange.numbers = [("101", "Birinchi", "yangi"), ("103", "Operator 3", "p103")]

    synced = _state(client.post(f"{URL}/sync", headers=boss))

    assert [(row.number, row.title, row.is_gone) for row in synced.extensions] == [
        ("101", "Birinchi", False),
        ("103", "Operator 3", False),
        ("102", "Operator 2", True),
    ]
    assert synced.extensions[2].user is None
    kept = db.scalar(select(PhoneExtension).where(PhoneExtension.number == "101"))
    assert kept is not None and crypto.decrypt(kept.sip_password) == "yangi"
    refused = client.patch(
        f"{URL}/extensions/{gone_id}", json={"user_id": str(seller.id)}, headers=boss
    )
    assert refused.status_code == 409 and refused.json()["code"] == "extension_gone"


def test_a_changed_utel_password_asks_for_the_login_again(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    state = _state(client.put(f"{URL}/connection", json=LOGIN, headers=boss))
    seat = state.extensions[0].id
    exchange.token = "2|yangi"

    ended = client.post(f"{URL}/sync", headers=boss)
    assert ended.status_code == 409
    assert ended.json()["code"] == "exchange_session_ended"

    # Signing in again to the same exchange keeps the numbers as they were.
    again = _state(client.put(f"{URL}/connection", json=LOGIN, headers=boss))
    assert again.extensions[0].id == seat
    assert db.scalar(select(func.count()).select_from(PhoneConnection)) == 1
    assert len(_ours(exchange)) == 1


def test_another_exchange_starts_the_numbers_anew(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    first = _state(client.put(f"{URL}/connection", json=LOGIN, headers=boss))
    old_key = db.scalar(select(PhoneConnection.hook_key))

    second = _state(
        client.put(f"{URL}/connection", json=LOGIN | {"tenant": "utc380"}, headers=boss)
    )

    assert second.connection is not None and second.connection.tenant == "utc380"
    assert {row.id for row in second.extensions}.isdisjoint(
        row.id for row in first.extensions
    )
    assert db.scalar(select(func.count()).select_from(PhoneConnection)) == 1
    (ours,) = _ours(exchange)
    assert old_key not in ours["url"]


def test_utel_events_are_written_down_by_the_key(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    client.put(f"{URL}/connection", json=LOGIN, headers=boss)
    key = db.scalar(select(PhoneConnection.hook_key))
    nested = {
        "time": "10:00:00",
        "data": {
            "name": "call_started",
            "call": {"id": "abc-1", "src": "998901234567"},
        },
    }
    flat = {"name": "call_saved", "call_history": {"call_id": "abc-1", "duration": 12}}

    assert client.post(f"/webhooks/utel/{key}", json=nested).json() == {"ok": True}
    assert client.post(f"/webhooks/utel/{key}", json=flat).json() == {"ok": True}
    assert client.post("/webhooks/utel/boshqa-kalit", json=flat).status_code == 404
    assert client.post(f"/webhooks/utel/{key}", content=b"salom").status_code == 400
    assert client.post(f"/webhooks/utel/{key}", json=[1, 2]).status_code == 400
    assert (
        client.post(f"/webhooks/utel/{key}", content=b"x" * 300_000).status_code == 413
    )

    rows = list(db.scalars(select(PhoneHookEvent).order_by(PhoneHookEvent.received_at)))
    assert [(row.name, row.call_id) for row in rows] == [
        ("call_started", "abc-1"),
        ("call_saved", "abc-1"),
    ]
    assert rows[0].payload == nested
    state = _state(client.get(URL, headers=boss))
    assert state.connection is not None
    assert state.connection.events_last_day == 2
    assert state.connection.last_event_at is not None


def test_disconnecting_forgets_everything_and_takes_our_address_off(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    client.put(f"{URL}/connection", json=LOGIN, headers=boss)
    key = db.scalar(select(PhoneConnection.hook_key))
    client.post(f"/webhooks/utel/{key}", json={"name": "call_ended"})

    gone = _state(client.delete(f"{URL}/connection", headers=boss))

    assert not gone.connected
    assert exchange.hook_rows == [OTHER_HOOK]
    for model in (PhoneConnection, PhoneExtension, PhoneHookEvent):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert client.post(f"/webhooks/utel/{key}", json={}).status_code == 404
    assert client.delete(f"{URL}/connection", headers=boss).status_code == 409


def test_an_erased_staff_member_leaves_their_number_free(
    client: TestClient, db: Session, exchange: Exchange
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    _staff(db, "sotuv@office.test", Role.SALES)
    seller = db.scalar(select(User).where(User.email == "sotuv@office.test"))
    assert seller is not None
    state = _state(client.put(f"{URL}/connection", json=LOGIN, headers=boss))
    client.patch(
        f"{URL}/extensions/{state.extensions[0].id}",
        json={"user_id": str(seller.id)},
        headers=boss,
    )

    delete_rows(db, User.__table__, User.id == seller.id)
    db.commit()

    after = _state(client.get(URL, headers=boss))
    assert len(after.extensions) == 2 and after.extensions[0].user is None
