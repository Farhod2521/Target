"""The ads screens' answers in the cabinet's own shapes, read with no translation.

The browser used to join the list with its figures, read amounts back out of
their words and filter the rows itself (``bridges/campaigns.ts``); these
answers carry all of that as it is drawn.
"""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.metrics.models import MetricsDaily
from tests.pg.conftest import sign_up
from tests.pg.test_ads_manage import _mirror
from tests.pg.test_cabinet_flows import _cabinet


def _cabinet_with_figures(client: TestClient, db: Session) -> tuple[dict[str, str], Any]:
    headers = sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    assert owner is not None
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    campaign = _mirror(db, owner, account.id)
    campaign.daily_budget_minor = 150_000
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
    today = utcnow().date()
    for back in range(1, 4):
        db.add(
            MetricsDaily(
                owner_id=owner.id,
                provider=PROVIDER,
                external_id="s_1",
                ad_account_id=account.id,
                level="adset",
                campaign_external_id="c_1",
                adset_external_id="s_1",
                date=today - timedelta(days=back),
                spend_minor=500,
                currency=account.currency or "USD",
                impressions=1000,
                synced_at=utcnow(),
            )
        )
    db.commit()
    return headers, campaign


def test_the_list_carries_its_figures_as_numbers(client: TestClient, db: Session) -> None:
    headers, campaign = _cabinet_with_figures(client, db)

    body = client.get("/api/v1/campaigns?period=7d", headers=headers).json()

    row = body["campaigns"][0]
    assert row["id"] == str(campaign.id) and row["externalId"] == "c_1"
    assert row["dailyBudget"]["minor"] == 150_000
    assert {"minor", "currency", "exponent"} <= set(row["dailyBudget"])
    assert row["metrics"]["spent"]["minor"] == 1_500
    assert row["origin"] == "here" and row["status"] == "active"
    assert row["controls"]["canPause"] is True
    assert body["summary"]["spent"]["minor"] == 1_500
    assert body["sources"] == {"all": 1, "here": 1, "network": 0, "other_account": 0}
    assert body["state"] == "ready"


def test_the_filters_are_applied_on_the_server(client: TestClient, db: Session) -> None:
    headers, _ = _cabinet_with_figures(client, db)

    paused = client.get("/api/v1/campaigns?status=paused", headers=headers).json()
    elsewhere = client.get("/api/v1/campaigns?source=network", headers=headers).json()
    nonsense = client.get("/api/v1/campaigns?status=x&period=y", headers=headers)

    assert paused["campaigns"] == [] and paused["counts"] == {
        "running": 1,
        "paused": 0,
        "all": 1,
    }
    assert elsewhere["sourceFallback"] is True and len(elsewhere["campaigns"]) == 1
    assert nonsense.status_code == 200


def test_a_row_unfolds_into_its_groups_and_adverts(
    client: TestClient, db: Session
) -> None:
    headers, campaign = _cabinet_with_figures(client, db)

    tree = client.get(f"/api/v1/campaigns/{campaign.id}/tree", headers=headers)
    ads = client.get(f"/api/v1/campaigns/{campaign.id}/ads", headers=headers)

    assert tree.status_code == 200, tree.text
    body = tree.json()
    assert body["split"] is False
    group = body["groups"][0]
    assert group["externalId"] == "s_1" and group["isLast"] is True
    assert group["ads"][0]["externalId"] == "a_1"
    assert group["ads"][0]["position"] == 1
    assert group["ads"][0]["canSwap"] is True
    assert [ad["externalId"] for ad in ads.json()] == ["a_1"]


def test_a_campaign_page_comes_in_one_answer(client: TestClient, db: Session) -> None:
    headers, campaign = _cabinet_with_figures(client, db)

    page = client.get(f"/api/v1/campaigns/{campaign.id}", headers=headers)

    assert page.status_code == 200, page.text
    body = page.json()
    assert body["id"] == str(campaign.id) and body["network"]["id"] == "meta"
    assert body["dailyBudget"]["minor"] == 150_000
    assert body["ads"][0]["externalId"] == "a_1"
    assert body["controls"]["canPause"] is True
    assert {"hasChoice", "hasFigures", "periods"} <= set(body["panel"])
    assert body["access"]["readOnly"] in (True, False)


def test_a_campaign_is_switched_by_its_own_id(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, campaign = _cabinet_with_figures(client, db)
    path = f"/api/v1/campaigns/{campaign.id}/pause"

    first = client.post(path, headers=headers)
    again = client.post(path, headers=headers)

    assert first.status_code == 200, first.text
    state = first.json()
    assert state["level"] == "campaign" and state["externalId"] == "c_1"
    assert state["pending"] is True and state["action"]["status"] == "pending"
    assert again.status_code == 409
    assert again.json()["code"] == "refused"
