"""Money sent back through Rahmat (Multicard): from its cabinet, or from the office."""

import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from paykit import registry
from paykit.multicard import MulticardAdapter, MulticardClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.common.db import utcnow
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.billing.constants import InvoiceStatus, TransactionState
from app.modules.billing.models import Invoice, PaymentTransaction, Subscription
from tests.pg.test_office_actions import _shop, _staff
from tests.pg.test_office_payments import _attempt, _bill

SECRET = "test-secret"
URL = "/api/v1/office/payments"


class Rahmat:
    """Multicard's ``/payment/{uuid}``, faked at the HTTP edge."""

    def __init__(self) -> None:
        self.status: dict[str, str] = {}
        self.refuse_cancel = False
        self.cancelled: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return httpx.Response(
                200, json={"token": "t", "expiry": "2099-01-01 00:00:00"}
            )
        uuid = request.url.path.removeprefix("/payment/")
        if uuid not in self.status:
            return httpx.Response(
                404, json={"success": False, "error": {"code": "ERROR_NOT_FOUND"}}
            )
        if request.method == "DELETE":
            if self.refuse_cancel:
                return httpx.Response(
                    400,
                    json={
                        "success": False,
                        "error": {"code": "ERROR_TRANS_NOT_READY", "details": "Yopiq"},
                    },
                )
            self.cancelled.append(uuid)
            self.status[uuid] = "revert"
        return httpx.Response(
            200,
            json={"success": True, "data": {"uuid": uuid, "status": self.status[uuid]}},
        )


@pytest.fixture
def rahmat(
    pg_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[Rahmat]:
    monkeypatch.setattr("app.common.db.SessionLocal", pg_factory)
    fake = Rahmat()
    registry.clear()
    registry.register(
        "multicard",
        MulticardAdapter(
            client=MulticardClient(
                base_url="https://dev-mesh.multicard.uz",
                application_id="app",
                secret=SECRET,
                transport=httpx.MockTransport(fake),
            ),
            store_id="6",
            secret=SECRET,
            callback_url="https://api.example.uz/webhooks/pay/multicard",
            decimal_places=2,
            ofd_mxik="10305008002000000",
            ofd_package_code="1545643",
            ofd_name="TargetologAI obunasi",
        ),
    )
    yield fake
    registry.clear()


def _paid(db: Session, *, number: str, uuid: str) -> tuple[Invoice, Subscription]:
    shop, plan = _shop(db)
    live = db.scalar(select(Subscription).where(Subscription.owner_id == shop.id))
    assert live is not None
    bill = _bill(
        db,
        plan,
        shop,
        number,
        status=InvoiceStatus.PAID,
        paid_at=utcnow(),
        subscription_id=live.id,
        applied_days=30,
    )
    attempt = _attempt(
        db, bill, state=TransactionState.PERFORMED, performed_at=utcnow()
    )
    attempt.provider, attempt.external_id = "multicard", uuid
    db.commit()
    return bill, live


def _webhook(bill: Invoice, uuid: str, status: str) -> dict[str, object]:
    body: dict[str, object] = {
        "uuid": uuid,
        "invoice_id": bill.number,
        "amount": bill.amount_minor,
        "status": status,
    }
    body["sign"] = hashlib.sha1(
        f"{uuid}{bill.number}{bill.amount_minor}{SECRET}".encode()
    ).hexdigest()
    return body


def test_a_revert_from_the_cabinet_takes_the_days_back_once_rahmat_says_so(
    client: TestClient, db: Session, rahmat: Rahmat
) -> None:
    bill, live = _paid(db, number="TA-51", uuid="pay-51")
    ends = live.expires_at
    rahmat.status["pay-51"] = "success"

    # A captured webhook replayed with "revert": the signature does not cover
    # the status, so Rahmat is asked, and it still holds the payment as paid.
    replayed = client.post(
        "/webhooks/pay/multicard",
        content=json.dumps(_webhook(bill, "pay-51", "revert")),
    )
    assert replayed.status_code == 200 and replayed.json() == {"success": True}
    db.expire_all()
    assert db.get(Invoice, bill.id).status == InvoiceStatus.PAID
    assert db.get(Subscription, live.id).expires_at == ends

    rahmat.status["pay-51"] = "revert"
    for _ in range(2):
        answer = client.post(
            "/webhooks/pay/multicard",
            content=json.dumps(_webhook(bill, "pay-51", "revert")),
        )
        assert answer.json() == {"success": True}
    db.expire_all()
    assert db.get(Invoice, bill.id).status == InvoiceStatus.REFUNDED
    attempt = db.scalar(select(PaymentTransaction))
    assert attempt is not None and attempt.state == TransactionState.REFUNDED
    assert db.get(Subscription, live.id).expires_at == ends - timedelta(days=30)
    assert rahmat.cancelled == []


def test_only_the_super_admin_sends_the_money_back(
    client: TestClient, db: Session, rahmat: Rahmat
) -> None:
    bill, live = _paid(db, number="TA-52", uuid="pay-52")
    ends = live.expires_at
    rahmat.status["pay-52"] = "success"
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    root_user, root = _staff(db, email="root@office.test", superuser=True)
    path = f"{URL}/invoices/{bill.id}/refund"

    assert client.post(path, headers=owner, json={"reason": "x"}).status_code == 404
    assert client.post(path, headers=root, json={"reason": ""}).status_code == 422
    assert rahmat.cancelled == []
    listed = client.get(f"{URL}/invoices", headers=root).json()["rows"]
    assert [row["refundable"] for row in listed] == [True]

    done = client.post(path, headers=root, json={"reason": "Mijoz so'radi"})
    assert done.status_code == 200, done.text
    assert rahmat.cancelled == ["pay-52"]
    listed = client.get(f"{URL}/invoices", headers=root).json()["rows"]
    assert [row["refundable"] for row in listed] == [False]
    db.expire_all()
    assert db.get(Invoice, bill.id).status == InvoiceStatus.REFUNDED
    assert db.get(Subscription, live.id).expires_at == ends - timedelta(days=30)
    trace = db.scalar(
        select(StaffAction).where(StaffAction.kind == str(ActionKind.INVOICE_REFUNDED))
    )
    assert trace is not None and trace.actor_id == root_user.id
    assert trace.reason == "Mijoz so'radi" and trace.detail["invoice"] == "TA-52"

    # Rahmat's own revert webhook follows the cancel: it changes nothing more.
    echo = client.post(
        "/webhooks/pay/multicard",
        content=json.dumps(_webhook(bill, "pay-52", "revert")),
    )
    assert echo.json() == {"success": True}
    db.expire_all()
    assert db.get(Subscription, live.id).expires_at == ends - timedelta(days=30)

    again = client.post(path, headers=root, json={"reason": "x"})
    assert again.status_code == 400 and again.json()["code"] == "nothing_to_refund"
    assert rahmat.cancelled == ["pay-52"]


def test_a_refused_refund_leaves_the_bill_paid(
    client: TestClient, db: Session, rahmat: Rahmat
) -> None:
    bill, live = _paid(db, number="TA-53", uuid="pay-53")
    ends = live.expires_at
    rahmat.status["pay-53"] = "success"
    rahmat.refuse_cancel = True
    _, root = _staff(db, email="root@office.test", superuser=True)

    refused = client.post(
        f"{URL}/invoices/{bill.id}/refund", headers=root, json={"reason": "x"}
    )
    assert refused.status_code == 400 and refused.json()["code"] == "refund_refused"
    assert "Yopiq" in refused.json()["detail"]
    db.expire_all()
    assert db.get(Invoice, bill.id).status == InvoiceStatus.PAID
    assert db.get(Subscription, live.id).expires_at == ends
    assert db.scalar(select(StaffAction)) is None


def test_a_bill_rahmat_did_not_take_is_not_refunded_here(
    client: TestClient, db: Session, rahmat: Rahmat
) -> None:
    shop, plan = _shop(db)
    paid_payme = _bill(db, plan, shop, "TA-54", status=InvoiceStatus.PAID)
    _attempt(db, paid_payme, state=TransactionState.PERFORMED)
    unpaid = _bill(db, plan, None, "TA-55")
    db.commit()
    _, root = _staff(db, email="root@office.test", superuser=True)

    listed = client.get(f"{URL}/invoices", headers=root).json()["rows"]
    assert not any(row["refundable"] for row in listed)
    for bill in (paid_payme, unpaid):
        answer = client.post(
            f"{URL}/invoices/{bill.id}/refund", headers=root, json={"reason": "x"}
        )
        assert (
            answer.status_code == 400 and answer.json()["code"] == "nothing_to_refund"
        )
    db.expire_all()
    assert db.get(Invoice, paid_payme.id).status == InvoiceStatus.PAID


def test_a_bill_with_pages_is_not_refunded_by_hand(
    client: TestClient, db: Session, rahmat: Rahmat
) -> None:
    bill, _ = _paid(db, number="TA-56", uuid="pay-56")
    bill.pages = 2
    db.commit()
    rahmat.status["pay-56"] = "success"
    _, root = _staff(db, email="root@office.test", superuser=True)

    listed = client.get(f"{URL}/invoices", headers=root).json()["rows"]
    assert [row["refundable"] for row in listed] == [False]
    answer = client.post(
        f"{URL}/invoices/{bill.id}/refund", headers=root, json={"reason": "x"}
    )
    assert answer.status_code == 400 and answer.json()["code"] == "refund_not_whole"
    assert rahmat.cancelled == []
    db.expire_all()
    assert db.get(Invoice, bill.id).status == InvoiceStatus.PAID


def test_the_card_tells_the_super_admin_which_bill_can_go_back(
    client: TestClient, db: Session, rahmat: Rahmat
) -> None:
    bill, _ = _paid(db, number="TA-57", uuid="pay-57")
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    _, root = _staff(db, email="root@office.test", superuser=True)
    card = f"/api/v1/office/customers/{bill.owner_id}"

    def bills(head: dict[str, str]) -> list[tuple[str, bool]]:
        answer = client.get(card, headers=head)
        assert answer.status_code == 200, answer.text
        return [
            (row["id"], row["refundable"]) for row in answer.json()["money"]["invoices"]
        ]

    assert bills(root) == [(str(bill.id), True)]
    assert bills(owner) == [(str(bill.id), False)]

    bill.seats = 1
    db.commit()
    assert bills(root) == [(str(bill.id), False)]
