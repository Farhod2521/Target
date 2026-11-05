"""Google Ads: an account under a manager, a campaign's end date and places."""

from datetime import date, timedelta
from typing import Any

import pytest
from adskit.dto import AccountStateDTO
from fastapi.testclient import TestClient
from googleadskit import CustomerDTO, ManagerToken
from googleadskit.campaigns import GoogleCampaigns
from googleadskit.locations import GoogleAudiences
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Campaign, GoogleLaunch
from app.modules.ads.services.access import token_for
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import AdAccount
from app.modules.integrations.services.sync import store_google_accounts
from tests.pg.test_launch_api import _ready
from tests.pg.test_launch_drafts import _google

CAMPAIGN = "customers/111/campaigns/5"
TASHKENT, BUKHARA = "geoTargetConstants/1", "geoTargetConstants/3"


def _campaign(db: Session, *, user: User, account: AdAccount) -> None:
    account.is_active = account.is_current = True
    db.add(
        Campaign(
            owner_id=user.id,
            provider="google",
            external_id=CAMPAIGN,
            ad_account_id=account.id,
            name="Qidiruv",
            delivery="active",
            status="ENABLED",
            currency="USD",
            daily_budget_minor=700,
            synced_at=utcnow(),
        )
    )
    db.commit()


def _no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.ads.services.access.token_for", lambda *, ad_account: "tok"
    )


def _log(db: Session, action: str) -> ActionLog:
    log = db.scalar(select(ActionLog).where(ActionLog.action == action))
    assert log is not None
    return log


def test_an_account_under_a_manager_keeps_its_manager(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _auth, user = _ready(client, db)
    account, _launch = _google(db, monkeypatch, user)

    store_google_accounts(
        db,
        connection=account.connection,
        accounts=[
            CustomerDTO(
                id="333",
                name="Mijoz",
                currency="UZS",
                time_zone="Asia/Tashkent",
                status="ENABLED",
                login_customer_id="900",
            )
        ],
    )
    db.commit()

    found = db.scalar(select(AdAccount).where(AdAccount.external_id == "333"))
    assert found is not None and found.login_customer_id == "900"


def test_every_call_on_such_an_account_goes_through_the_manager(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _auth, user = _ready(client, db)
    account, _launch = _google(db, monkeypatch, user)
    account.login_customer_id = "900"
    connect = type("Connect", (), {"access_token": lambda _s, *, stored: "tok"})()
    bundle = type("Bundle", (), {"connect": connect})()
    monkeypatch.setattr(
        "app.modules.ads.services.access.registry.get", lambda _n: bundle
    )
    monkeypatch.setattr("app.modules.ads.services.access.decrypt", lambda _t: "stored")

    token = token_for(ad_account=account)

    assert isinstance(token, ManagerToken)
    assert (str(token), token.login_customer_id) == ("tok", "900")


def test_a_campaign_gets_its_last_day(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    account, _launch = _google(db, monkeypatch, user)
    _campaign(db, user=user, account=account)
    last = date.today() + timedelta(days=30)

    pressed = client.post(
        "/api/v1/google/end-date",
        json={"id": CAMPAIGN, "endDate": last.isoformat()},
        headers=auth,
    )

    assert pressed.status_code == 200, pressed.text
    log = _log(db, ActionType.END_TIME_SET)
    assert log.target_level == "campaign"
    assert log.request_payload["end_time"].startswith(last.isoformat())


def test_a_last_day_already_gone_is_refused(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    account, _launch = _google(db, monkeypatch, user)
    _campaign(db, user=user, account=account)

    pressed = client.post(
        "/api/v1/google/end-date",
        json={"id": CAMPAIGN, "endDate": "2020-01-01"},
        headers=auth,
    )

    assert pressed.status_code == 400, pressed.text


def test_places_are_replaced_with_the_old_ones_kept_to_undo(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    account, _launch = _google(db, monkeypatch, user)
    _campaign(db, user=user, account=account)
    _no_token(monkeypatch)
    monkeypatch.setattr(
        GoogleAudiences,
        "read_targeting",
        lambda _self, *, ref, token: {
            "places": [TASHKENT],
            "names": {TASHKENT: "Tashkent"},
        },
    )

    shown = client.get(f"/api/v1/google/places?id={CAMPAIGN}", headers=auth)
    pressed = client.post(
        "/api/v1/google/places",
        json={"id": CAMPAIGN, "places": [BUKHARA, BUKHARA]},
        headers=auth,
    )

    assert shown.json() == {"places": [{"id": TASHKENT, "name": "Tashkent"}]}
    assert pressed.status_code == 200, pressed.text
    log = _log(db, ActionType.TARGETING_SWAP)
    assert log.request_payload["targeting"] == {"places": [BUKHARA]}
    assert log.previous_state["targeting"] == {"places": [TASHKENT]}


def test_a_campaign_is_not_left_without_places(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    account, _launch = _google(db, monkeypatch, user)
    _campaign(db, user=user, account=account)

    pressed = client.post(
        "/api/v1/google/places", json={"id": CAMPAIGN, "places": []}, headers=auth
    )

    assert pressed.status_code in (400, 422), pressed.text


def _ready_to_create(db: Session, launch: GoogleLaunch) -> None:
    launch.status = "ready"
    launch.ai_written_at = utcnow()
    db.commit()


def _state(paying: bool | None) -> Any:
    def read(_self: GoogleCampaigns, *, account: Any, token: str) -> AccountStateDTO:
        return AccountStateDTO(
            ref=account, standing="active", has_payment_method=paying
        )

    return read


def test_an_account_google_cannot_charge_is_stopped_before_anything_is_made(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    account, launch = _google(db, monkeypatch, user)
    account.is_active = account.is_current = True
    _ready_to_create(db, launch)
    _no_token(monkeypatch)
    monkeypatch.setattr(GoogleCampaigns, "read_account", _state(False))

    pressed = client.post(f"/api/v1/google/launch/{launch.id}/create", headers=auth)

    assert pressed.status_code == 400, pressed.text
    assert "to'lov usuli" in pressed.json()["detail"]
    assert not any(name.endswith("create_google_campaign_task") for name, _ in queued)


def test_not_knowing_about_billing_lets_the_press_through(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    account, launch = _google(db, monkeypatch, user)
    account.is_active = account.is_current = True
    _ready_to_create(db, launch)
    _no_token(monkeypatch)
    monkeypatch.setattr(GoogleCampaigns, "read_account", _state(None))

    pressed = client.post(f"/api/v1/google/launch/{launch.id}/create", headers=auth)

    assert pressed.status_code < 400, pressed.text
    assert any(name.endswith("create_google_campaign_task") for name, _ in queued)
