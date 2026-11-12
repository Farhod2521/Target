"""Whom UTeL puts an incoming call through to, against PostgreSQL."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.telephony.models import PhoneExtension
from tests.pg.test_boards_sales import _client
from tests.pg.test_telephony_calls import _card, _event, _saved, office  # noqa: F401
from tests.pg.test_telephony_live import _moment, _recent
from tests.pg.test_telephony_settings import exchange  # noqa: F401

NOBODY = {"extension": None, "module": None, "contact_name": None}


def _ask(client: TestClient, office: dict[str, Any], number: str) -> dict[str, Any]:  # noqa: F811
    answer = client.get(f"{office['hook']}/route", params={"number": number})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_a_client_reaches_whoever_works_their_card(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    owner = _client(db, "shop@shop.test")
    card = _card(db, owner, "sales", "new_lead")
    card.manager_id = office["people"]["sotuv@office.test"].id
    db.commit()
    to_seller = {"extension": "101", "module": 101, "contact_name": "Shop"}

    # However UTeL writes the number, and however it asks.
    for number in ("901234567", "998901234567", "+998901234567"):
        assert _ask(client, office, number) == to_seller
    posted = client.post(
        f"{office['hook']}/route",
        json={"number": "901234567", "external_number": "555550220", "module": 6001},
    )
    assert posted.json() == to_seller

    # Their person is on a call: the group takes it.
    client.post(
        office["hook"],
        json=_moment("dial_answered", "busy", src="935550011", answered_by="101"),
    )
    assert _ask(client, office, "901234567") == NOBODY | {"contact_name": "Shop"}
    client.post(office["hook"], json=_moment("call_ended", "busy"))
    assert _ask(client, office, "901234567") == to_seller

    # A closed card puts nobody through.
    card.closed_at = utcnow()
    db.commit()
    assert _ask(client, office, "901234567") == NOBODY | {"contact_name": "Shop"}


def test_the_card_moved_last_wins_and_a_person_without_a_number_is_skipped(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    owner = _client(db, "shop@shop.test")
    sales = _card(db, owner, "sales", "new_lead")
    sales.manager_id = office["people"]["sotuv@office.test"].id
    db.commit()
    support = _card(db, owner, "support", "in_progress")
    support.manager_id = office["people"]["yordam@office.test"].id
    db.commit()

    assert _ask(client, office, "901234567")["extension"] == "102"

    # Support's number is taken away: the seller is next.
    seat = db.scalar(select(PhoneExtension).where(PhoneExtension.number == "102"))
    assert seat is not None
    seat.user_id = None
    db.commit()
    assert _ask(client, office, "901234567")["extension"] == "101"

    # The seller no longer works here.
    seller = db.get(User, office["people"]["sotuv@office.test"].id)
    assert seller is not None
    seller.is_active = False
    db.commit()
    assert _ask(client, office, "901234567")["extension"] is None


def test_a_caller_with_no_card_reaches_whoever_spoke_with_them_last(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    client.post(
        office["hook"],
        json=_event(_saved("a", src="935550011", dst="101", at=_recent(60))),
    )
    client.post(
        office["hook"],
        json=_event(
            _saved("b", src="102", dst="935550011", kind="Outgoing", at=_recent(5))
        ),
    )
    client.post(
        office["hook"],
        json=_event(
            _saved(
                "c",
                src="935550011",
                dst="101",
                status="Not answered",
                talk=0,
                at=_recent(1),
            )
        ),
    )

    assert _ask(client, office, "935550011") == {
        "extension": "102",
        "module": 102,
        "contact_name": None,
    }


def test_nobody_is_always_a_json_object(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    for number in ("", "777", "axlat", "935550011"):
        assert _ask(client, office, number) == NOBODY
    assert client.post(f"{office['hook']}/route", content=b"").json() == NOBODY
    assert client.post(f"{office['hook']}/route", content=b"[1]").json() == NOBODY
    unknown = client.get("/webhooks/utel/boshqa-kalit/route", params={"number": "1"})
    assert unknown.status_code == 404 and unknown.json()
