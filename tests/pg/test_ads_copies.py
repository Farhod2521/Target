"""TZ 2.1-2.3: Meta's copies of a campaign, a group and an advert.

A campaign is copied alone, then each group, then each advert: only an
advert's copy takes creative parameters, and each copied creative refuses
Meta's creative changes (TZ 7.1). A campaign's and a group's copy is paused;
an advert put into a running group is active, into a new one paused.
"""

import json
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
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign, MediaAsset
from app.modules.ads.services import copies
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from tests.pg.test_ads_additions import Fake
from tests.pg.test_ads_additions import _signed_in as _additions_signed_in
from tests.pg.test_ads_additions import fake as _fake  # noqa: F401 - the fixture
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
        False,
    )
    assert group["status"] == "INHERITED_FROM_SOURCE" and group["suffix"] == ""
    kind, advert = meta.calls[2]
    assert (kind, advert["ad_id"], advert["adset_id"]) == ("ad", "a_1", "s_new2")
    # TZ 7.1: the copied creative refuses every Meta change.
    features = advert["creative"]["degrees_of_freedom_spec"]["creative_features_spec"]
    assert {row["enroll_status"] for row in features.values()} == {"OPT_OUT"}
    assert len(meta.calls) == 3
    log = db.scalar(
        select(ActionLog).where(ActionLog.action == ActionType.COPY_CAMPAIGN)
    )
    assert log is not None and log.status == ActionStatus.APPLIED


def test_a_group_is_copied_then_each_advert(
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
                "creative": copies._opted_out(),
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


# -- TZ 2.3: a new creative ------------------------------------------------------------


@pytest.fixture
def launcher(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Fake:
    """The launcher's calls kept; every picture is the account's own."""
    monkeypatch.setattr(copies, "foreign_pictures", lambda **_: [])
    return request.getfixturevalue("_fake")


def _with_button(db: Session, owner: Any, button: dict[str, Any]) -> None:
    creative = db.scalar(select(AdCreative).where(AdCreative.owner_id == owner.id))
    assert creative is not None
    creative.story_raw = {
        "page_id": "page_1",
        "link_data": {
            "message": "Buyurtma bering",
            "link": "https://tort.uz",
            "call_to_action": button,
        },
    }
    db.commit()


def _picture_id(db: Session, owner: Any) -> str:
    asset = db.scalar(select(MediaAsset).where(MediaAsset.owner_id == owner.id))
    assert asset is not None
    return str(asset.id)


def _applied(db: Session, owner: Any) -> str:
    log = db.scalar(
        select(ActionLog).where(
            ActionLog.owner_id == owner.id, ActionLog.action == ActionType.COPY_AD
        )
    )
    assert log is not None
    return copies.apply_copy(db, log_id=str(log.id))


def test_a_new_creative_in_the_same_group_starts_at_once(
    client: TestClient, db: Session, queued: list, meta: Meta, launcher: Fake
) -> None:
    headers, owner, _campaign = _additions_signed_in(client, db)
    _with_button(
        db, owner, {"type": "LEARN_MORE", "value": {"link": "https://tort.uz"}}
    )

    form = client.get("/api/v1/campaigns/ads/a_1/copy/creative", headers=headers)
    assert form.status_code == 200, form.text
    body = form.json()
    assert body["button"] == "LEARN_MORE" and body["canSwap"] is True
    assert body["buttons"][0] == {"key": "LEARN_MORE", "label": "Batafsil"}
    assert "SHOP_NOW" in {row["key"] for row in body["buttons"]}

    answer = client.post(
        "/api/v1/campaigns/ads/a_1/copy",
        json={
            "into": "s_1",
            "creative": {
                "message": "Bugun chegirma",
                "picture": _picture_id(db, owner),
                "button": "SHOP_NOW",
            },
        },
        headers=headers,
    )

    assert answer.status_code == 202, answer.text
    assert _applied(db, owner) == "applied"
    made = dict(launcher.calls)
    block = made["creative"]["story"]["link_data"]
    assert block["message"] == "Bugun chegirma"
    assert block["image_hash"] == "hash_1"
    assert block["call_to_action"] == {
        "type": "SHOP_NOW",
        "value": {"link": "https://tort.uz"},
    }
    assert made["ad"]["adset"].id == "s_1" and made["ad"]["status"] == "ACTIVE"
    assert made["ad"]["name"].endswith(" — nusxa")
    assert meta.calls == []


def test_a_new_creative_in_a_new_group_is_paused(
    client: TestClient, db: Session, queued: list, meta: Meta, launcher: Fake
) -> None:
    headers, owner, _campaign = _additions_signed_in(client, db)

    answer = client.post(
        "/api/v1/campaigns/ads/a_1/copy",
        json={"into": "new", "creative": {"headline": "Tort"}},
        headers=headers,
    )

    assert answer.status_code == 202, answer.text
    assert _applied(db, owner) == "applied"
    ((kind, group),) = meta.calls
    assert kind == "adset" and group["deep_copy"] is False
    assert group["status"] == "PAUSED"
    made = dict(launcher.calls)
    assert made["ad"]["adset"].id == "s_new1" and made["ad"]["status"] == "PAUSED"


def test_a_button_of_another_kind_is_refused(
    client: TestClient, db: Session, queued: list, meta: Meta, launcher: Fake
) -> None:
    headers, owner, _campaign = _additions_signed_in(client, db)
    _with_button(
        db,
        owner,
        {"type": "SIGN_UP", "value": {"lead_gen_form_id": "f_1", "link": "x"}},
    )

    answer = client.post(
        "/api/v1/campaigns/ads/a_1/copy",
        json={"into": "s_1", "creative": {"button": "SHOP_NOW"}},
        headers=headers,
    )

    assert answer.status_code in (400, 409, 422), answer.text
    assert db.scalar(select(ActionLog)) is None


def test_a_chat_button_keeps_its_word(
    client: TestClient, db: Session, queued: list, meta: Meta, launcher: Fake
) -> None:
    headers, owner, _campaign = _additions_signed_in(client, db)
    _with_button(
        db,
        owner,
        {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}},
    )

    form = client.get("/api/v1/campaigns/ads/a_1/copy/creative", headers=headers)

    assert [row["key"] for row in form.json()["buttons"]] == ["WHATSAPP_MESSAGE"]


def test_a_picture_from_another_library_is_refused(
    client: TestClient, db: Session, queued: list, meta: Meta, launcher: Fake
) -> None:
    headers, _owner, _campaign = _additions_signed_in(client, db)

    answer = client.post(
        "/api/v1/campaigns/ads/a_1/copy",
        json={
            "into": "s_1",
            "creative": {"picture": "00000000-0000-0000-0000-000000000000"},
        },
        headers=headers,
    )

    assert answer.status_code == 422, answer.text


def test_a_new_creative_takes_a_new_greeting(
    client: TestClient, db: Session, queued: list, meta: Meta, launcher: Fake
) -> None:
    headers, owner, _campaign = _additions_signed_in(client, db)
    _with_button(
        db, owner, {"type": "MESSAGE_PAGE", "value": {"app_destination": "MESSENGER"}}
    )

    form = client.get("/api/v1/campaigns/ads/a_1/copy/creative", headers=headers)
    assert form.json()["welcome"] == {
        "text": "",
        "questions": [],
        "maxQuestions": 4,
        "maxChars": 80,
    }
    answer = client.post(
        "/api/v1/campaigns/ads/a_1/copy",
        json={
            "into": "s_1",
            "creative": {
                "welcome": {"text": "Salom", "questions": [{"title": "Narxi?"}]}
            },
        },
        headers=headers,
    )

    assert answer.status_code == 202, answer.text
    assert _applied(db, owner) == "applied"
    sent = json.loads(
        dict(launcher.calls)["creative"]["story"]["link_data"]["page_welcome_message"]
    )
    assert sent["text_format"]["message"]["ice_breakers"] == [{"title": "Narxi?"}]


def test_a_campaigns_copy_ready_is_said_in_the_list(
    client: TestClient,
    db: Session,
    queued: list,
    meta: Meta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.notifications.selectors.inbox_cabinet import _copies

    headers, owner, campaign = _signed_in(client, db)
    answer = client.post(f"/api/v1/campaigns/{campaign.id}/copy", headers=headers)
    assert answer.status_code == 202, answer.text
    assert _copies(db, owner=owner, now=utcnow()) == []

    assert _run(db, monkeypatch, campaign) == "applied"

    (item,) = _copies(db, owner=owner, now=utcnow())
    assert item.title == "Kampaniya nusxasi tayyor: «Bahor — nusxa»"
    assert item.level == "news" and item.key.startswith("copy:")


def test_a_copy_that_fails_half_way_is_taken_back(
    client: TestClient,
    db: Session,
    queued: list,
    meta: Meta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adskit.errors import InvalidRequest

    headers, _owner, campaign = _signed_in(client, db)
    removed: list[str] = []

    def refuse(**kw: Any) -> str:
        raise InvalidRequest("no", code="100")

    monkeypatch.setattr(copies, "copy_ad", refuse)
    monkeypatch.setattr(
        copies, "delete_object", lambda **kw: removed.append(kw["object_id"]) or True
    )
    client.post(f"/api/v1/campaigns/{campaign.id}/copy", headers=headers)

    assert _run(db, monkeypatch, campaign) == "failed"
    # The group first, then the campaign it was made in.
    assert removed == ["s_new2", "c_new"]


def test_a_group_does_not_go_where_its_budget_would_not_fit(
    client: TestClient, db: Session, queued: list, meta: Meta
) -> None:
    headers, owner, campaign = _signed_in(client, db)
    db.add(
        Campaign(
            owner_id=owner.id,
            provider=campaign.provider,
            external_id="c_cbo",
            ad_account_id=campaign.ad_account_id,
            name="Byudjeti kampaniyada",
            delivery="paused",
            status="PAUSED",
            daily_budget_minor=1000,
            synced_at=utcnow(),
        )
    )
    db.commit()

    places = client.get("/api/v1/campaigns/adsets/s_1/copy", headers=headers).json()
    answer = client.post(
        "/api/v1/campaigns/adsets/s_1/copy", json={"into": "c_cbo"}, headers=headers
    )

    assert "c_cbo" not in [row["id"] for row in places["places"]]
    assert answer.status_code in (400, 404), answer.text
