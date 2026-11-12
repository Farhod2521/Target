"""The reader's browser phone against PostgreSQL: who gets which number's
password, and what a refusal by the exchange does."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.backoffice.constants import Role
from app.modules.telephony.models import PhoneExtension
from app.modules.telephony.schemas import MyPhoneOut, TelephonyOut
from tests.pg.test_boards_me import _staff
from tests.pg.test_telephony_calls import office  # noqa: F401
from tests.pg.test_telephony_settings import exchange  # noqa: F401

URL = "/api/v2/office/telephony"


def _me(client: TestClient, head: dict[str, str]) -> MyPhoneOut:
    answer = client.get(f"{URL}/me", headers=head)
    assert answer.status_code == 200, answer.text
    assert answer.headers["cache-control"] == "no-store"
    return MyPhoneOut.model_validate(answer.json())


def _refused(client: TestClient, head: dict[str, str]) -> MyPhoneOut:
    answer = client.post(f"{URL}/me/refused", headers=head)
    assert answer.status_code == 200, answer.text
    return MyPhoneOut.model_validate(answer.json())


def test_a_person_gets_their_own_number_s_password_and_nobody_else_s(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    seller = _me(client, office["seller"])
    assert seller.enabled and seller.reason == "" and seller.extension == "101"
    assert seller.sip is not None
    assert seller.sip.model_dump() == {
        "socket": "wss://utc181.utel.uz:8089/ws",
        "domain": "utc181.utel.uz",
        "uri": "sip:101@utc181.utel.uz",
        "login": "101",
        "password": "p101",
    }
    assert seller.rules.retry_max == 3 and seller.rules.never_retry_codes == [401, 403]
    helper = _me(client, office["helper"])
    assert helper.sip is not None and helper.sip.password == "p102"

    # No number: the lead and the superuser have none here.
    for head in (office["lead"], office["boss"]):
        none = _me(client, head)
        assert (none.enabled, none.reason, none.sip) == (False, "no_extension", None)
        assert none.reason_label
    outsider = _staff(db, "moliya@office.test", Role.FINANCE)
    assert client.get(f"{URL}/me", headers=outsider).status_code == 404
    assert client.get(f"{URL}/me").status_code == 401


def test_no_phone_when_it_is_switched_off_or_nothing_is_connected(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    seat = db.scalar(select(PhoneExtension.id).where(PhoneExtension.number == "101"))
    client.patch(
        f"{URL}/extensions/{seat}", json={"softphone": False}, headers=office["boss"]
    )
    off = _me(client, office["seller"])
    assert (off.enabled, off.reason, off.extension, off.sip) == (
        False,
        "softphone_off",
        "101",
        None,
    )

    client.delete(f"{URL}/connection", headers=office["boss"])
    gone = _me(client, office["seller"])
    assert (gone.enabled, gone.reason, gone.extension) == (False, "not_connected", None)
    assert not _refused(client, office["seller"]).enabled


def test_a_refusal_with_a_changed_password_hands_over_the_new_one(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    office["exchange"].numbers = [
        ("101", "Operator 1", "yangi"),
        ("102", "Op 2", "p102"),
    ]

    again = _refused(client, office["seller"])

    assert again.enabled and again.sip is not None and again.sip.password == "yangi"


def test_a_refusal_with_the_same_password_stops_the_phone_until_the_office_acts(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    stopped = _refused(client, office["seller"])
    assert (stopped.enabled, stopped.reason, stopped.sip) == (
        False,
        "sip_refused",
        None,
    )
    assert not _me(client, office["seller"]).enabled
    # The other person's phone is untouched.
    assert _me(client, office["helper"]).enabled

    state = TelephonyOut.model_validate(client.get(URL, headers=office["boss"]).json())
    assert state.extensions[0].sip_refused_at is not None
    assert state.extensions[1].sip_refused_at is None

    # Reading the numbers again with the password unchanged keeps it stopped.
    client.post(f"{URL}/sync", headers=office["boss"])
    assert not _me(client, office["seller"]).enabled
    # A changed password starts it again.
    office["exchange"].numbers = [
        ("101", "Operator 1", "yangi"),
        ("102", "Op 2", "p102"),
    ]
    client.post(f"{URL}/sync", headers=office["boss"])
    assert _me(client, office["seller"]).enabled

    # So does the office switching the browser phone on again.
    assert not _refused(client, office["seller"]).enabled
    client.patch(
        f"{URL}/extensions/{state.extensions[0].id}",
        json={"softphone": True},
        headers=office["boss"],
    )
    assert _me(client, office["seller"]).enabled


def test_a_refusal_while_utel_is_silent_still_stops_the_phone(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    office["exchange"].down = True
    assert _refused(client, office["seller"]).reason == "sip_refused"


def test_a_number_utel_dropped_gives_no_phone(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    office["exchange"].numbers = [("102", "Op 2", "p102")]
    client.post(f"{URL}/sync", headers=office["boss"])
    assert _me(client, office["seller"]).reason == "no_extension"
