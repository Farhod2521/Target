from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.services import start_trial
from app.modules.businesses.models import BusinessCategory
from app.modules.integrations.models import AdAccount, PageAccount, ProviderConnection
from tests.pg.conftest import sign_up


def _cabinet(db: Session, user: User) -> tuple[AdAccount, PageAccount]:
    connection = ProviderConnection(
        owner_id=user.id,
        provider=PROVIDER,
        external_user_id="fb-1",
        token_encrypted=b"x",
        token_fingerprint=fingerprint("x"),
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=user.id,
        provider=PROVIDER,
        external_id="act_1",
        connection_id=connection.id,
        name="Asosiy",
        currency="USD",
        timezone="Asia/Tashkent",
        may_advertise=True,
    )
    page = PageAccount(
        owner_id=user.id,
        provider=PROVIDER,
        external_id="page_1",
        connection_id=connection.id,
        name="Bahor kafesi",
        token_encrypted=b"x",
        token_fingerprint="p",
    )
    db.add_all([account, page])
    db.commit()
    return account, page


def test_trial_then_connections_billing_and_profile(
    client: TestClient, db: Session
) -> None:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    start_trial(db, user=user, now=utcnow())
    db.add(
        BusinessCategory(
            key="restaurant",
            label_uz="Restoran",
            label_ru="Ресторан",
            label_en="Restaurant",
            preset_key="restaurant",
            position=0,
        )
    )
    db.commit()
    _cabinet(db, user)

    status = client.get("/api/v1/billing/status", headers=auth)
    assert status.status_code == 200, status.text
    assert status.json()["subscription"]["status"] == "trial"

    chosen = client.post(
        "/api/v1/connections/meta/page", json={"external_id": "page_1"}, headers=auth
    )
    assert chosen.status_code == 200, chosen.text

    cabinet = client.get("/api/v1/connections/cabinet", headers=auth)
    assert cabinet.status_code == 200, cabinet.text
    assert [p["external_id"] for p in cabinet.json()["pages"]] == ["page_1"]

    saved = client.put(
        "/api/v1/business",
        json={
            "name": "Bahor",
            "category": "restaurant",
            "country_code": "UZ",
            "timezone": "Asia/Tashkent",
        },
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["category_label"] == "Ресторан"

    profile = client.get("/api/v1/business", headers=auth)
    assert profile.json()["business"]["direction_key"] == "restaurant"

    custom = client.put(
        "/api/v1/business",
        json={
            "name": "Bahor",
            "category": "__custom__",
            "custom_label": "Non sexi",
            "country_code": "UZ",
            "timezone": "Asia/Tashkent",
        },
        headers=auth,
    )
    assert custom.json()["category_label"] == "Non sexi"


def test_plans_checkout_and_promo_refusal(client: TestClient, db: Session) -> None:
    auth = sign_up(client)
    db.add(
        Plan(
            code="pro",
            name="Pro",
            tagline="",
            features="* Tez\n# Asosiy\nBir narsa",
            price=30,
            currency="USD",
            period_days=30,
            max_adsets=10,
            daily_chat_requests=20,
            llm_cost_limit_minor=1000,
            included_pages=2,
            included_google_accounts=0,
            extra_page_price=10,
            is_one_time=False,
            is_active=True,
            sort_order=1,
        )
    )
    db.commit()

    plans = client.get("/api/v1/billing?plan=pro", headers=auth)
    assert plans.status_code == 200, plans.text
    assert plans.json()["chosen"]["due_minor"] == 3000

    no_provider = client.post(
        "/api/v1/billing/checkout", json={"plan": "pro"}, headers=auth
    )
    assert no_provider.status_code == 400
    invoice = db.scalar(select(Invoice))
    assert invoice is not None and invoice.amount_minor == 3000

    unknown = client.post("/api/v1/billing/promo", json={"code": "NOPE"}, headers=auth)
    assert unknown.status_code == 400

    wait = client.get(f"/api/v1/billing/invoice/{invoice.number}", headers=auth)
    assert wait.status_code == 200 and wait.json()["polling"] is True

    history = client.get("/api/v1/billing/history", headers=auth)
    assert history.status_code == 200
    assert history.json()["invoices_total"] == 1
    assert db.scalar(select(Subscription)) is None
