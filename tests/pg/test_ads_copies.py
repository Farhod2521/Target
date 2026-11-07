"""TZ 2.1-2.3: Meta's copies of a campaign, a group and an advert.

A deep copy is one call only while it carries three adverts or fewer; a
bigger tree is copied a level at a time. A campaign's and a group's copy is
paused; an advert put into a running group is active, into a new one paused.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from adskit.dto import StatusDTO
from adskit.refs import ExternalRef
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.actions import executor
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.services import copies
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from tests.pg.test_campaign_rename import _signed_in


class Meta:
    """Meta's copy edge, kept: every call and what it answered."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def campaign(self, **kw: Any) -> str:
        self.calls.append(("campaign", kw))
        return "c_new"

    def adset(self, **kw: Any) -> str:
        self.calls.append(("adset", kw))
        return f"s_new{len(self.calls)}"

    def ad(self, **kw: Any) -> str:
        self.calls.append(("ad", kw))
        return f"a_new{len(self.calls)}"


class Status:
    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        return StatusDTO(ref=ref, status="ACTIVE", delivery="active")


@pytest.fixture
def meta(monkeypatch: pytest.MonkeyPatch) -> Meta:
    found = Meta()
    monkeypatch.setattr(copies, "copy_campaign", found.campaign)
    monkeypatch.setattr(copies, "copy_adset", found.adset)
    monkeypatch.setattr(copies, "copy_ad", found.ad)
    monkeypatch.setattr(
        executor,
        "registry",
        SimpleNamespace(get=lambda _: SimpleNamespace(campaigns=Status())),
    )
    return found


def _run(db: Session, monkeypatch: pytest.MonkeyPatch, campaign: Campaign) -> str:
    account = campaign.ad_account
    monkeypatch.setattr(
        executor, "target_account_and_token", lambda **_: (account, "token")
    )
    log = db.scalar(select(ActionLog).order_by(ActionLog.created_at.desc()))
    assert log is not None
    return copies.apply_copy(db, log_id=str(log.id))


def _more_ads(db: Session, group: AdSet, count: int) -> None:
    for n in range(count):
        db.add(
            Ad(
                owner_id=group.owner_id,
                provider=group.provider,
                external_id=f"a_extra{n}",
                adset_id=group.id,
                name=f"Reklama {n}",
                delivery="active",
                status="ACTIVE",
                synced_at=utcnow(),
            )
        )
    db.commit()


def test_a_campaign_is_copied_paused_with_its_groups_and_adverts(
    client: TestClient,
    db: Session,
    queued: list,
    meta: Meta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _owner, campaign = _signed_in(client, db)

    answer = client.post(f"/api/v1/campaigns/{campaign.id}/copy", headers=headers)

    assert answer.status_code == 202, answer.text
    assert queued[-1][0].endswith("apply_copy_task")
    assert _run(db, monkeypatch, campaign) == "applied"
    assert meta.calls[0] == (
        "campaign",
        {
            "campaign_id": "c_1",
            "suffix": " — nusxa",
            "token": "token",
            "dry_run": True,
        },
    )
    kind, group = meta.calls[1]
    assert kind == "adset"
    assert (group["adset_id"], group["campaign_id"], group["deep_copy"]) == (
        "s_1",
        "c_new",
        True,
    )
    assert group["status"] == "INHERITED_FROM_SOURCE" and group["suffix"] == ""
    assert len(meta.calls) == 2
    log = db.scalar(
        select(ActionLog).where(ActionLog.action == ActionType.COPY_CAMPAIGN)
    )
    assert log is not None and log.status == ActionStatus.APPLIED


def test_more_than_three_adverts_are_copied_one_by_one(
    client: TestClient,
    db: Session,
    queued: list,
    meta: Meta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _owner, campaign = _signed_in(client, db)
    group = campaign.adsets[0]
    _more_ads(db, group, 3)

    answer = client.post("/api/v1/campaigns/adsets/s_1/copy", json={}, headers=headers)

    assert answer.status_code == 202, answer.text
    assert _run(db, monkeypatch, campaign) == "applied"
    kind, copied = meta.calls[0]
    assert kind == "adset" and copied["deep_copy"] is False
    assert copied["status"] == "PAUSED" and copied["suffix"] == " — nusxa"
    assert copied["campaign_id"] == "c_1"
    assert [kind for kind, _ in meta.calls[1:]] == ["ad"] * 4
    assert {call["adset_id"] for _, call in meta.calls[1:]} == {"s_new1"}


def test_a_group_goes_into_another_campaign_of_the_account(
    client: TestClient,
    db: Session,
    queued: list,
    meta: Meta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, owner, campaign = _signed_in(client, db)
    other = Campaign(
        owner_id=owner.id,
        provider=campaign.provider,
        external_id="c_2",
        ad_account_id=campaign.ad_account_id,
        name="Qish",
        delivery="paused",
        status="PAUSED",
        synced_at=utcnow(),
    )
    db.add(other)
    db.commit()

    places = client.get("/api/v1/campaigns/adsets/s_1/copy", headers=headers).json()
    assert [(row["id"], row["own"]) for row in places["places"]] == [
        ("c_1", True),
        ("c_2", False),
    ]
    answer = client.post(
        "/api/v1/campaigns/adsets/s_1/copy", json={"into": "c_2"}, headers=headers
    )

    assert answer.status_code == 202, answer.text
    assert _run(db, monkeypatch, campaign) == "applied"
    assert meta.calls[0][1]["campaign_id"] == "c_2"


def test_a_campaign_the_owner_does_not_hold_is_refused(
    client: TestClient, db: Session, queued: list, meta: Meta
) -> None:
    headers, _owner, _campaign = _signed_in(client, db)

    answer = client.post(
        "/api/v1/campaigns/adsets/s_1/copy", json={"into": "c_x"}, headers=headers
    )

    assert answer.status_code in (400, 404), answer.text
    assert db.scalar(select(ActionLog)) is None


def test_an_advert_in_its_running_group_is_copied_active(
    client: TestClient,
    db: Session,
    queued: list,
    meta: Meta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _owner, campaign = _signed_in(client, db)

    places = client.get("/api/v1/campaigns/ads/a_1/copy", headers=headers).json()
    assert places["places"][0] == {
        "id": "s_1",
        "name": "Guruh",
        "running": True,
        "own": True,
    }
    answer = client.post(
        "/api/v1/campaigns/ads/a_1/copy", json={"into": "s_1"}, headers=headers
    )

    assert answer.status_code == 202, answer.text
    assert _run(db, monkeypatch, campaign) == "applied"
    assert meta.calls == [
        (
            "ad",
            {
                "ad_id": "a_1",
                "adset_id": "s_1",
                "status": "ACTIVE",
                "suffix": " — nusxa",
                "token": "token",
                "dry_run": True,
            },
        )
    ]


def test_an_advert_in_a_new_group_is_copied_paused(
    client: TestClient,
    db: Session,
    queued: list,
    meta: Meta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _owner, campaign = _signed_in(client, db)

    answer = client.post(
        "/api/v1/campaigns/ads/a_1/copy", json={"into": "new"}, headers=headers
    )

    assert answer.status_code == 202, answer.text
    assert _run(db, monkeypatch, campaign) == "applied"
    (group_kind, group), (ad_kind, ad) = meta.calls
    assert group_kind == "adset" and group["deep_copy"] is False
    assert group["status"] == "PAUSED"
    assert ad_kind == "ad" and ad["adset_id"] == "s_new1" and ad["status"] == "PAUSED"
