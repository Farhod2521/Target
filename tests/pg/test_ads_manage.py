"""Ads against PostgreSQL: the page scope over a mirror, and asking for a change."""

from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import selectors, services
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.exceptions import AlreadyInState, ChangeInFlight
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
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
    owner = User(email="ads@example.com", full_name="Ads", password="!", date_joined=utcnow())
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
    assert selectors.accounts_that_paid_by_page(db, owner=owner) == {page.id: {account.id}}
    assert selectors.ad_label(db, owner=owner, external_id="a_1").campaign_name == "Bahor"
    assert selectors.campaign_on_page(db, owner=owner, campaign=campaign)
    assert [row.external_id for row in selectors.campaigns_for(db, owner=owner)] == ["c_1"]

    log = services.request_pause(
        db, user=owner, level=ManagedLevel.CAMPAIGN, external_id="c_1"
    )
    db.commit()
    assert log.status == "pending" and log.action == "pause"
    assert queued and queued[-1][0].endswith("apply_change_task")

    try:
        services.request_pause(db, user=owner, level=ManagedLevel.CAMPAIGN, external_id="c_1")
    except ChangeInFlight:
        db.rollback()
    else:  # pragma: no cover
        raise AssertionError("a second press must be turned away")

    db.execute(ActionLog.__table__.delete())
    campaign.delivery = "paused"
    db.commit()
    try:
        services.request_pause(db, user=owner, level=ManagedLevel.CAMPAIGN, external_id="c_1")
    except AlreadyInState:
        db.rollback()
    else:  # pragma: no cover
        raise AssertionError("pausing a paused campaign is refused")
    assert db.scalar(select(ActionLog.id)) is None
