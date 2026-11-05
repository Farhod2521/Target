"""Facebook on a customer's office card, against PostgreSQL with Django's
foreign keys: disconnecting it whole, and sending the verdicts nights left."""

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import encrypt
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Campaign, CampaignLaunch
from app.modules.audit.models import ActionLog
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.backoffice.schemas import (
    ActivityOut,
    FacebookForgottenOut,
    FacebookHoldingsOut,
    SignalBookOut,
    SignalsSentOut,
)
from app.modules.backoffice.selectors import signals as book
from app.modules.billing.models import Subscription
from app.modules.businesses.models import Business
from app.modules.content_studio.models import BrandKit
from app.modules.crm.models import CrmCard, CrmMember, CrmSetup, CrmStage
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PagePair,
    PixelAccount,
    ProviderConnection,
)
from app.modules.leads.models import Lead, LeadForm, LeadSignal
from app.modules.leads.services import signals
from tests.pg.test_crm_http import _auth, _member, _owner, _running
from tests.pg.test_lead_signals import Port, _pixel
from tests.pg.test_office_crm import WHY, _count, _staff

URL = "/api/v1/office/customers"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())


@pytest.fixture
def port(monkeypatch: pytest.MonkeyPatch) -> Port:
    fake = Port()
    meta = SimpleNamespace(get=lambda _: SimpleNamespace(conversions=fake))
    monkeypatch.setattr(signals, "registry", meta)
    monkeypatch.setattr(book, "registry", meta)
    monkeypatch.setattr(signals.settings, "ads_dry_run", False)
    return fake


def _forget(client: TestClient, owner: User, head: dict[str, str], email: str) -> Any:
    return client.post(
        f"{URL}/{owner.id}/facebook/forget",
        headers=head,
        json={"email": email, "reason": WHY},
    )


def _furnished(client: TestClient, db: Session) -> User:
    """A paying owner with everything Meta brings, plus what they bought."""
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _member(client, head, "vali@example.com")
    account = db.scalars(select(AdAccount).where(AdAccount.owner_id == owner.id)).one()
    page = db.scalars(select(PageAccount).where(PageAccount.owner_id == owner.id)).one()
    _pixel(db, owner, account)
    db.add(
        Campaign(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id="c_1",
            ad_account_id=account.id,
            name="Kampaniya",
        )
    )
    db.add(
        Business(
            user_id=owner.id,
            page_id=page.id,
            name="Gullar do'koni",
            timezone="Asia/Tashkent",
        )
    )
    db.add(BrandKit(owner_id=owner.id, page_id=page.id, brand_name="Gullar"))
    subscription = db.scalars(
        select(Subscription).where(Subscription.owner_id == owner.id)
    ).one()
    subscription.extra_pages = 2
    subscription.ad_account_id = account.id
    subscription.setup_completed_at = utcnow()
    owner.prepared_at = utcnow()
    db.commit()
    return owner


def test_the_dialog_counts_what_would_go(client: TestClient, db: Session) -> None:
    owner = _furnished(client, db)
    boss = _staff(db, Role.OWNER, "boss@office.test")

    answer = client.get(f"{URL}/{owner.id}/facebook", headers=boss)

    assert answer.status_code == 200, answer.text
    held = FacebookHoldingsOut.model_validate(answer.json())
    assert held.connected is True
    assert (held.pages, held.ad_accounts, held.pixels) == (1, 1, 1)
    assert (held.launches, held.campaigns, held.leads) == (1, 1, 3)
    assert (held.cards, held.managers, held.brand_kits) == (3, 1, 1)


def test_only_the_owner_may_disconnect(client: TestClient, db: Session) -> None:
    owner = _furnished(client, db)
    support = _staff(db, Role.SUPPORT, "help@office.test")

    assert client.get(f"{URL}/{owner.id}/facebook", headers=support).status_code == 404
    assert _forget(client, owner, support, owner.email).status_code == 404
    assert _count(db, PageAccount, owner) == 1


def test_a_wrong_address_changes_nothing(client: TestClient, db: Session) -> None:
    owner = _furnished(client, db)
    boss = _staff(db, Role.OWNER, "boss@office.test")

    answer = _forget(client, owner, boss, "boshqa@example.com")

    assert answer.status_code == 400
    assert "Facebook uzilmadi" in answer.json()["detail"]
    assert _count(db, PageAccount, owner) == 1
    assert _count(db, Lead, owner) == 3


def test_disconnecting_takes_everything_meta_brought(
    client: TestClient, db: Session
) -> None:
    owner = _furnished(client, db)
    logs = _count(db, ActionLog, owner)
    boss = _staff(db, Role.OWNER, "boss@office.test")

    answer = _forget(client, owner, boss, " CRM@example.com ")

    assert answer.status_code == 200, answer.text
    done = FacebookForgottenOut.model_validate(answer.json())
    assert "Obuna saqlandi" in done.message
    assert done.kept_business is True
    gone = (
        ProviderConnection,
        AdAccount,
        PageAccount,
        PagePair,
        PixelAccount,
        CampaignLaunch,
        Campaign,
        Lead,
        LeadForm,
        LeadSignal,
        CrmCard,
        CrmStage,
        CrmSetup,
        CrmMember,
        BrandKit,
    )
    for model in gone:
        assert _count(db, model, owner) == 0, model
    assert db.scalar(select(User).where(User.email == "vali@example.com")) is None

    subscription = db.scalars(
        select(Subscription).where(Subscription.owner_id == owner.id)
    ).one()
    assert subscription.status == "active"
    assert subscription.extra_pages == 2
    assert subscription.ad_account_id is None
    assert subscription.setup_completed_at is None
    db.refresh(owner)
    assert owner.prepared_at is None
    business = db.scalars(select(Business).where(Business.user_id == owner.id)).one()
    assert (business.name, business.page_id) == ("Gullar do'koni", None)

    # The history stays; the office's row says how much went.
    assert _count(db, ActionLog, owner) >= logs
    row = db.scalar(
        select(StaffAction).where(
            StaffAction.owner_id == owner.id,
            StaffAction.kind == ActionKind.FACEBOOK_FORGOTTEN,
        )
    )
    assert row is not None
    assert row.reason == WHY
    assert (row.detail["pages"], row.detail["leads"], row.detail["cards"]) == (1, 3, 3)

    again = _forget(client, owner, boss, owner.email)
    assert again.status_code == 409


def test_the_same_facebook_may_come_back(client: TestClient, db: Session) -> None:
    owner = _furnished(client, db)
    boss = _staff(db, Role.OWNER, "boss@office.test")
    assert _forget(client, owner, boss, owner.email).status_code == 200

    db.add(
        ProviderConnection(
            owner_id=owner.id,
            provider=PROVIDER,
            external_user_id="fb-1",
            token_encrypted=b"x",
            token_fingerprint="again",
        )
    )
    db.commit()

    cabinet = client.get("/api/v1/connections/cabinet", headers=_auth(owner))
    assert cabinet.status_code == 200, cabinet.text
    assert cabinet.json()["pages"] == []


def _signal(
    db: Session, owner: User, *, stage: str, status: str = "pending", days: int = 1
) -> LeadSignal:
    lead = db.scalars(
        select(Lead).where(Lead.owner_id == owner.id).order_by(Lead.leadgen_id)
    ).first()
    account = db.scalars(select(AdAccount).where(AdAccount.owner_id == owner.id)).one()
    assert lead is not None
    row = LeadSignal(
        owner_id=owner.id,
        lead_id=lead.id,
        ad_account_id=account.id,
        stage=stage,
        source="internal",
        status=status,
        occurred_at=utcnow() - timedelta(days=days),
    )
    db.add(row)
    db.commit()
    return row


def _ready(db: Session) -> User:
    owner = _owner(db)
    account = db.scalars(select(AdAccount).where(AdAccount.owner_id == owner.id)).one()
    account.connection.token_encrypted = encrypt("token")
    db.commit()
    return owner


def _book(client: TestClient, owner: User, head: dict[str, str]) -> SignalBookOut:
    answer = client.get(f"{URL}/{owner.id}/signals", headers=head)
    assert answer.status_code == 200, answer.text
    return SignalBookOut.model_validate(answer.json())


def _send(client: TestClient, owner: User, head: dict[str, str]) -> Any:
    return client.post(
        f"{URL}/{owner.id}/signals/send", headers=head, json={"reason": WHY}
    )


def test_a_night_without_a_pixel_waits_for_the_button(
    client: TestClient, db: Session, port: Port
) -> None:
    owner = _ready(db)
    _signal(db, owner, stage="qualified")
    _signal(db, owner, stage="unqualified")
    help_ = _staff(db, Role.SUPPORT, "help@office.test")

    seen = _book(client, owner, help_)
    assert seen.sendable == 2
    assert [b.reason for b in seen.blockers] == ["no_pixel"]
    day = seen.days[0]
    assert day.state == "unsent"
    assert (day.stages["qualified"].pending, day.stages["unqualified"].pending) == (
        1,
        1,
    )

    refused = _send(client, owner, help_)
    assert refused.status_code == 200, refused.text
    assert "Piksel tanlanmagan" in refused.json()["message"]
    assert refused.json()["waiting"] == 2
    assert port.calls == []

    account = db.scalars(select(AdAccount).where(AdAccount.owner_id == owner.id)).one()
    _pixel(db, owner, account)
    db.commit()
    sent = _send(client, owner, help_)
    assert sent.status_code == 200, sent.text
    out = SignalsSentOut.model_validate(sent.json())
    assert (out.sent, out.waiting) == (2, 0)
    assert "2 ta signal" in out.message
    assert sorted(stage for _, stage in port.sent) == ["qualified", "unqualified"]

    after = _book(client, owner, help_)
    assert after.sendable == 0
    assert after.blockers == []
    assert after.days[0].state == "sent"
    assert after.days[0].datasets == ["px_1"]
    assert after.days[0].sent_at is not None
    assert _send(client, owner, help_).status_code == 409

    kinds = [
        row.detail["sent"]
        for row in db.scalars(
            select(StaffAction).where(
                StaffAction.owner_id == owner.id,
                StaffAction.kind == ActionKind.SIGNALS_SENT,
            )
        )
    ]
    assert sorted(kinds) == [0, 2]


def test_a_refused_row_gets_another_try(
    client: TestClient, db: Session, port: Port
) -> None:
    owner = _ready(db)
    account = db.scalars(select(AdAccount).where(AdAccount.owner_id == owner.id)).one()
    _pixel(db, owner, account)
    row = _signal(db, owner, stage="qualified", status="failed")
    row.last_error = "bad lead_id"
    db.commit()
    help_ = _staff(db, Role.SUPPORT, "help@office.test")
    assert _book(client, owner, help_).days[0].errors == ["bad lead_id"]

    port.refuse = row.lead.leadgen_id
    again = _send(client, owner, help_)
    assert again.status_code == 200
    db.refresh(row)
    assert row.status == "failed"

    port.refuse = ""
    assert _send(client, owner, help_).json()["sent"] == 1
    db.refresh(row)
    assert row.status == "sent"


def test_past_the_window_nothing_is_offered(
    client: TestClient, db: Session, port: Port
) -> None:
    owner = _ready(db)
    _signal(db, owner, stage="qualified", days=9)
    help_ = _staff(db, Role.SUPPORT, "help@office.test")

    assert _book(client, owner, help_).sendable == 0
    assert _send(client, owner, help_).status_code == 409


def _feed(
    client: TestClient, owner: User, head: dict[str, str], **params: Any
) -> dict[str, Any]:
    answer = client.get(f"{URL}/{owner.id}/activity", headers=head, params=params)
    assert answer.status_code == 200, answer.text
    return ActivityOut.model_validate(answer.json()).model_dump(mode="json")


def test_the_history_tells_who_did_what(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _member(client, head, "vali@example.com")
    db.add(
        ActionLog(
            owner_id=owner.id,
            actor_type="system",
            action="pause",
            target_provider=PROVIDER,
            target_level="campaign",
            target_external_id="c_1",
            status="failed",
            error_message="Meta rad etdi",
            idempotency_key="k-1",
        )
    )
    db.commit()
    boss = _staff(db, Role.OWNER, "boss@office.test")
    help_ = _staff(db, Role.SUPPORT, "help@office.test")
    assert _forget(client, owner, boss, owner.email).status_code == 200

    feed = _feed(client, owner, help_)
    rows = feed["rows"]
    titles = [row["title"] for row in rows]
    assert titles[0] == "Facebook to'liq uzildi"
    assert rows[0]["who"] == "staff" and rows[0]["text"] == WHY
    # The manager's own sign-in, filed on the owner's history under their name.
    signin = next(row for row in rows if row["title"] == "Tizimga kirdi")
    assert (signin["who"], signin["who_name"]) == ("manager", "vali@example.com")
    paused = next(row for row in rows if row["title"] == "To'xtatish")
    assert (paused["who"], paused["status"], paused["error"]) == (
        "system",
        "failed",
        "Meta rad etdi",
    )
    assert not any(row["detail"].get("leadgen_id") for row in rows)

    office = _feed(client, owner, help_, group="ofis")["rows"]
    assert [row["title"] for row in office] == ["Facebook to'liq uzildi"]
    system = _feed(client, owner, help_, who="system")["rows"]
    assert [row["title"] for row in system] == ["To'xtatish"]
    managers = _feed(client, owner, help_, who="manager")["rows"]
    assert {row["who"] for row in managers} == {"manager"}

    first = _feed(client, owner, help_, limit=2)
    assert len(first["rows"]) == 2 and first["next_before"]
    rest = _feed(client, owner, help_, before=first["next_before"], limit=200)
    ids = [r["id"] for r in first["rows"]] + [r["id"] for r in rest["rows"]]
    assert len(ids) == len(set(ids)) == len(rows)
    assert rest["next_before"] is None

    assert client.get(f"{URL}/{owner.id}/activity", headers=head).status_code == 404
    bad = client.get(f"{URL}/{owner.id}/activity", headers=help_, params={"group": "x"})
    assert bad.status_code == 422


def test_a_mini_app_sitting_is_one_sign_in(client: TestClient, db: Session) -> None:
    from app.modules.accounts.services import note_sign_in
    from app.modules.audit.models import Event

    owner = _owner(db)
    for _ in range(3):
        note_sign_in(db, user=owner, via="miniapp")
        db.commit()
    note_sign_in(db, user=owner, via="password", address="10.0.0.1")
    db.commit()

    rows = db.scalars(
        select(Event).where(Event.owner_id == owner.id, Event.name == "user.signed_in")
    ).all()
    assert sorted(row.payload["via"] for row in rows) == ["miniapp", "password"]
    assert owner.last_login is not None


def test_a_token_that_will_not_open_is_named_before_the_press(
    client: TestClient, db: Session, port: Port
) -> None:
    owner = _owner(db)
    account = db.scalars(select(AdAccount).where(AdAccount.owner_id == owner.id)).one()
    _pixel(db, owner, account)
    _signal(db, owner, stage="qualified")
    help_ = _staff(db, Role.SUPPORT, "help@office.test")

    assert [b.reason for b in _book(client, owner, help_).blockers] == ["connection"]
    answer = _send(client, owner, help_)
    assert "Meta ulanishi ishlamayapti" in answer.json()["message"]
