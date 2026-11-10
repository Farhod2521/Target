"""What the office says a launched campaign is doing: only what the copy of
Meta can vouch for - deleted ones are not listed, an old copy is not
"running", and an old copy is read again."""

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
from app.modules.ads.services.mirror import drop_ads, drop_adsets, drop_campaigns
from app.modules.backoffice.selectors.delivery import running_clause
from app.modules.integrations.models import AdAccount
from tests.pg.test_office_ads import _launched
from tests.pg.test_office_customers import URL

QUEUE = "app.modules.backoffice.services.ads_refresh.queue_sync"


def _fresh(db: Session, launch: CampaignLaunch) -> AdAccount:
    account = db.get(AdAccount, launch.ad_account_id)
    assert account is not None
    account.synced_at = utcnow()
    db.commit()
    return account


def _list(client: TestClient, owner: Any, headers: dict) -> dict:
    with patch(QUEUE) as queued:
        body = client.get(f"{URL}/{owner.id}/ads?period=all", headers=headers).json()
    body["_queued"] = queued.call_count
    return body


def test_a_fresh_copy_that_delivers_is_running(client: TestClient, db: Session) -> None:
    owner, launch, headers = _launched(client, db)
    _fresh(db, launch)

    body = _list(client, owner, headers)
    [row] = body["rows"]
    assert (row["delivery"], row["delivery_label"], row["is_running"]) == (
        "active",
        "Ishlayapti",
        True,
    )
    assert row["is_stale"] is False and row["synced_at"]
    assert body["running"] == 1 and body["deleted"] == 0
    assert body["refreshing"] is False and body["_queued"] == 0


def test_an_old_copy_is_not_called_running_and_is_read_again(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    account = _fresh(db, launch)
    old = utcnow() - timedelta(days=2)
    account.synced_at = old
    for campaign in db.scalars(select(Campaign).where(Campaign.owner_id == owner.id)):
        campaign.synced_at = old
    db.commit()

    body = _list(client, owner, headers)
    [row] = body["rows"]
    assert (row["delivery"], row["delivery_label"]) == ("stale", "Holati eskirgan")
    assert row["is_running"] is False and row["is_stale"] is True
    assert body["running"] == 0 and body["stale"] == 1
    assert body["refreshing"] is True and body["_queued"] == 1

    again = _list(client, owner, headers)
    assert again["_queued"] == 0, "one read per cooling window"

    month = client.get(f"{URL}/{owner.id}/ads?period=today", headers=headers).json()
    assert [r["delivery"] for r in month["rows"]] == ["stale"], "never hidden"


def test_a_campaign_deleted_on_meta_is_not_listed(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    launch.created_at = utcnow() - timedelta(hours=3)
    _fresh(db, launch)
    drop_ads(db, Ad.owner_id == owner.id)
    drop_adsets(db, AdSet.owner_id == owner.id)
    drop_campaigns(db, Campaign.owner_id == owner.id)
    db.commit()

    body = _list(client, owner, headers)
    assert body["rows"] == [] and body["deleted"] == 1
    assert body["running"] == 0
    assert [t["currency"] for t in body["deleted_totals"]] == ["USD"]
    assert body["totals"] == [] and body["summary"] == []


def test_a_campaign_not_read_yet_is_listed_as_such(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    account = _fresh(db, launch)
    account.synced_at = launch.created_at - timedelta(minutes=1)
    drop_ads(db, Ad.owner_id == owner.id)
    drop_adsets(db, AdSet.owner_id == owner.id)
    drop_campaigns(db, Campaign.owner_id == owner.id)
    db.commit()

    body = _list(client, owner, headers)
    [row] = body["rows"]
    assert (row["delivery"], row["delivery_label"]) == ("not_read", "Hali o'qilmagan")
    assert row["is_running"] is False and body["deleted"] == 0


def test_a_campaign_whose_adverts_are_all_gone_is_not_running(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    _fresh(db, launch)
    drop_ads(db, Ad.owner_id == owner.id)
    db.commit()

    body = _list(client, owner, headers)
    [row] = body["rows"]
    assert (row["delivery"], row["delivery_label"]) == ("no_ads", "Reklamasi qolmagan")
    assert row["is_running"] is False and body["running"] == 0


def test_switched_off_in_ads_manager_reads_paused(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    _fresh(db, launch)
    for campaign in db.scalars(select(Campaign).where(Campaign.owner_id == owner.id)):
        campaign.delivery = "paused"
    db.commit()

    body = _list(client, owner, headers)
    [row] = body["rows"]
    assert (row["delivery"], row["delivery_label"]) == ("paused", "To'xtatilgan")
    assert row["is_running"] is False and body["running"] == 0


def test_a_campaign_waiting_on_billing_is_not_running(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    _fresh(db, launch)
    for campaign in db.scalars(select(Campaign).where(Campaign.owner_id == owner.id)):
        campaign.delivery = "billing"
    db.commit()

    body = _list(client, owner, headers)
    [row] = body["rows"]
    assert (row["delivery"], row["delivery_label"]) == ("billing", "To'lov kutilmoqda")
    assert row["is_running"] is False


def test_a_campaign_on_with_no_advert_on_says_what_the_adverts_say(
    client: TestClient, db: Session
) -> None:
    """Meta keeps a campaign ACTIVE after its ad sets ended: never «Ishlayapti»."""
    owner, launch, headers = _launched(client, db)
    _fresh(db, launch)
    ads = list(db.scalars(select(Ad).where(Ad.owner_id == owner.id)))
    assert ads
    for ad in ads:
        ad.delivery = "finished"
    db.commit()

    [row] = _list(client, owner, headers)["rows"]
    assert (row["delivery"], row["delivery_label"], row["is_running"]) == (
        "finished",
        "Tugagan",
        False,
    )

    ads[0].delivery = "billing"
    db.commit()
    [row] = _list(client, owner, headers)["rows"]
    assert (row["delivery"], row["is_running"]) == ("billing", False)


def test_the_running_count_is_the_lists(client: TestClient, db: Session) -> None:
    owner, launch, _headers = _launched(client, db)
    _fresh(db, launch)
    now = utcnow()

    def running() -> int:
        return int(
            db.scalar(
                select(func.count(Campaign.id)).where(
                    Campaign.owner_id == owner.id, running_clause(now=now)
                )
            )
            or 0
        )

    assert running() == 1
    for campaign in db.scalars(select(Campaign).where(Campaign.owner_id == owner.id)):
        campaign.synced_at = now - timedelta(days=1)
    db.commit()
    assert running() == 0
    for campaign in db.scalars(select(Campaign).where(Campaign.owner_id == owner.id)):
        campaign.synced_at = now
    for ad in db.scalars(select(Ad).where(Ad.owner_id == owner.id)):
        ad.delivery = "paused"
    db.commit()
    assert running() == 0
