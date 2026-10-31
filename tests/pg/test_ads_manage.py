"""Ads against PostgreSQL: the page scope over a mirror, and asking for a change."""

from datetime import datetime, timedelta

import pytest
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import actions, selectors
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.exceptions import AlreadyInState, ChangeInFlight
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
from app.modules.ads.services.manage import close_stalled_changes, start_delivery
from app.modules.audit.models import ActionLog
from tests.pg.test_cabinet_flows import _cabinet


def _mirror(db: Session, owner: User, account_id: object) -> Campaign:
    now = utcnow()
    campaign = Campaign(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="c_1",
        ad_account_id=account_id,
        name="Bahor",
        delivery="active",
        status="ACTIVE",
        synced_at=now,
    )
    db.add(campaign)
    db.flush()
    adset = AdSet(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="s_1",
        campaign_id=campaign.id,
        name="Guruh",
        delivery="active",
        status="ACTIVE",
        promoted_object_raw={"page_id": "page_1"},
        synced_at=now,
    )
    db.add(adset)
    db.flush()
    db.add(
        Ad(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id="a_1",
            adset_id=adset.id,
            name="Reklama",
            delivery="active",
            status="ACTIVE",
            synced_at=now,
        )
    )
    db.commit()
    return campaign


def test_scope_labels_and_a_pause(db: Session, queued: list) -> None:
    owner = User(
        email="ads@example.com", full_name="Ads", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.commit()
    account, page = _cabinet(db, owner)
    page.is_current = True
    page.is_active = True
    account.is_active = True
    account.is_current = True
    db.commit()
    campaign = _mirror(db, owner, account.id)
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            page_id=page.id,
            provider=PROVIDER,
            status="created",
            created_refs={"campaign": "c_1", "adset": ["s_1"], "ad": ["a_1"]},
        )
    )
    db.commit()

    scope = selectors.page_scope(db, owner=owner)
    assert scope.page_of == {"s_1": "page_1"}
    assert selectors.all_launched_campaign_ids(db, owner=owner) == {"c_1"}
    assert selectors.accounts_that_paid_by_page(db, owner=owner) == {
        page.id: {account.id}
    }
    assert (
        selectors.ad_label(db, owner=owner, external_id="a_1").campaign_name == "Bahor"
    )
    assert selectors.campaign_on_page(db, owner=owner, campaign=campaign)
    assert [row.external_id for row in selectors.campaigns_for(db, owner=owner)] == [
        "c_1"
    ]

    log = actions.request(
        db,
        user=owner,
        ask=actions.Pause(level=ManagedLevel.CAMPAIGN, external_id="c_1"),
    )
    db.commit()
    assert log.status == "pending" and log.action == "pause"
    assert queued and queued[-1][0].endswith("apply_change_task")

    try:
        actions.request(
            db,
            user=owner,
            ask=actions.Pause(level=ManagedLevel.CAMPAIGN, external_id="c_1"),
        )
    except ChangeInFlight:
        db.rollback()
    else:  # pragma: no cover
        raise AssertionError("a second press must be turned away")

    db.execute(ActionLog.__table__.delete())
    campaign.delivery = "paused"
    db.commit()
    try:
        actions.request(
            db,
            user=owner,
            ask=actions.Pause(level=ManagedLevel.CAMPAIGN, external_id="c_1"),
        )
    except AlreadyInState:
        db.rollback()
    else:  # pragma: no cover
        raise AssertionError("pausing a paused campaign is refused")
    assert db.scalar(select(ActionLog.id)) is None


def test_campaigns_api(client, db: Session, queued: list) -> None:  # type: ignore[no-untyped-def]
    from tests.pg.conftest import sign_up

    headers = sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    campaign = _mirror(db, owner, account.id)

    listed = client.get("/api/v1/campaigns?status=all&source=all", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [row["externalId"] for row in body["campaigns"]] == ["c_1"]
    assert body["total"] == 1
    assert body["campaigns"][0]["controls"]["canPause"] is True

    detail = client.get(f"/api/v1/campaigns/{campaign.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    page = detail.json()
    assert page["groups"] is None  # one group: the page shows its adverts directly
    assert page["ads"][0]["externalId"] == "a_1"

    paused = client.post("/api/v1/campaigns/manage/campaign/c_1/pause", headers=headers)
    assert paused.status_code == 200, paused.text
    state = paused.json()
    assert state["refused"] is None and state["action"]["status"] == "pending"
    assert state["pending"] is True
    assert queued and queued[-1][0].endswith("apply_change_task")

    again = client.post(
        "/api/v1/campaigns/manage/campaign/c_1/pause", headers=headers
    ).json()
    assert again["refused"]

    polled = client.get(
        "/api/v1/campaigns/manage/campaign/c_1/state?tries=3", headers=headers
    )
    assert polled.status_code == 200 and polled.json()["tries"] == 4
    form = client.get("/api/v1/campaigns/manage/adset/s_1/budget", headers=headers)
    assert form.status_code == 200, form.text
    assert (
        client.get(
            "/api/v1/campaigns/manage/ad/nope/state", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/campaigns/{campaign.id}/history", headers=headers
        ).status_code
        == 200
    )


def test_every_level_of_a_start_goes_out_after_the_commit(
    db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sent early, a worker finds no row and the campaign stays off for good."""
    monkeypatch.setattr(
        "app.modules.billing.services.require_live_subscription", lambda *_a, **_k: None
    )
    owner, account = _owner_with_account(db)
    _mirror(db, owner, account.id)
    for row in (db.scalars(select(model)).one() for model in (Campaign, AdSet, Ad)):
        row.delivery, row.status = "paused", "PAUSED"
    db.commit()

    outcome = start_delivery(
        db,
        user=owner,
        targets=[("campaign", "c_1"), ("adset", "s_1"), ("ad", "a_1")],
    )
    assert outcome.refused == ()
    assert queued == []
    db.commit()

    assert len(queued) == 3


def test_a_change_no_worker_carried_out_is_closed(db: Session, queued: list) -> None:
    owner, _account = _owner_with_account(db)
    now = utcnow()
    old = _log(owner, "resume", key="old", created_at=now - timedelta(minutes=11))
    fresh = _log(owner, "resume", key="fresh", created_at=now)
    other = _log(owner, "budget_up", key="budget", created_at=now - timedelta(hours=1))
    db.add_all([old, fresh, other])
    db.commit()

    assert close_stalled_changes(db, now=now) == 1

    assert (old.status, old.error_code) == ("failed", "stalled")
    assert fresh.status == "pending"
    assert other.status == "pending"


def _owner_with_account(db: Session) -> tuple[User, object]:
    owner = User(
        email="start@example.com", full_name="Ads", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.commit()
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_current = account.is_active = True
    db.commit()
    return owner, account


def _log(owner: User, action: str, *, key: str, created_at: datetime) -> ActionLog:
    return ActionLog(
        owner_id=owner.id,
        action=action,
        target_level="campaign",
        target_external_id="c_1",
        target_provider=PROVIDER,
        idempotency_key=key,
        created_at=created_at,
    )
