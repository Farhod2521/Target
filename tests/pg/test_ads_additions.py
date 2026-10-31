"""A new group in a campaign and a new advert in a group, through the action layer."""

from types import SimpleNamespace
from typing import Any

import pytest
from adskit.dto import ActionResult, StatusDTO
from adskit.errors import InvalidRequest
from adskit.refs import ExternalRef
from fastapi.testclient import TestClient
from metaads import PROVIDER
from metaads.launcher import MetaLauncher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import selectors
from app.modules.ads.actions import executor
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign
from app.modules.ads.selectors import account_of
from app.modules.ads.services import additions
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.billing.services import start_trial
from tests.pg.conftest import sign_up
from tests.pg.test_ads_editing import _running
from tests.pg.test_cabinet_flows import _cabinet


class Port:
    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        return StatusDTO(ref=ref, status="ACTIVE", delivery="active")


class Fake:
    """What reached Meta, and a refusal when one is asked for."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.refuse_ad = False
        self.removed: list[str] = []

    def done(self, level: str, ref_id: str, **extra: Any) -> ActionResult:
        return ActionResult(
            ok=True,
            ref=ExternalRef(provider=PROVIDER, level=level, id=ref_id),  # type: ignore[arg-type]
            dry_run=False,
            **extra,
        )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Fake:
    seen = Fake()

    def adset_settings(_self: Any, *, adset: ExternalRef, token: str) -> dict[str, Any]:
        seen.calls.append(("settings", adset.id))
        return {
            "bid_strategy": "COST_CAP",
            "bid_amount": 90,
            "attribution_spec": [{"event_type": "CLICK_THROUGH", "window_days": 1}],
        }

    def create_adset(
        _self: Any, *, account: Any, spec: Any, token: str, dry_run: bool
    ) -> Any:
        seen.calls.append(("adset", spec))
        return seen.done("adset", "as_new", dropped={"interests": ["x"]})

    def restage_creative(_self: Any, **kwargs: Any) -> Any:
        seen.calls.append(("creative", kwargs))
        return seen.done("creative", "cr_new")

    def create_ad(_self: Any, **kwargs: Any) -> Any:
        seen.calls.append(("ad", kwargs))
        if seen.refuse_ad:
            raise InvalidRequest("no", code="100")
        return seen.done("ad", "ad_new")

    def remove(_self: Any, *, ref: ExternalRef, token: str, dry_run: bool) -> bool:
        seen.removed.append(ref.id)
        return True

    for name, method in (
        ("adset_settings", adset_settings),
        ("create_adset", create_adset),
        ("restage_creative", restage_creative),
        ("create_ad", create_ad),
        ("remove", remove),
    ):
        monkeypatch.setattr(MetaLauncher, name, method)
    monkeypatch.setattr(
        executor,
        "registry",
        SimpleNamespace(get=lambda _: SimpleNamespace(campaigns=Port())),
    )
    monkeypatch.setattr(
        executor,
        "target_account_and_token",
        lambda *, target, level: (
            account_of(target=target, level=level),
            "token",
        ),
    )
    monkeypatch.setattr(executor.settings, "ads_dry_run", False)
    monkeypatch.setattr(additions, "_queue", lambda *_: None)
    return seen


def _pending(db: Session, owner: User, action: str) -> ActionLog:
    log = db.scalar(
        select(ActionLog).where(
            ActionLog.owner_id == owner.id, ActionLog.action == action
        )
    )
    assert log is not None
    return log


def _signed_in(
    client: TestClient, db: Session
) -> tuple[dict[str, str], User, Campaign]:
    headers = sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    assert owner is not None
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    start_trial(db, user=owner, now=utcnow())
    db.commit()
    return headers, owner, _running(db, owner, account)


def test_a_new_group_is_a_paused_copy_with_its_own_name_and_money(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, owner, campaign = _signed_in(client, db)

    form = client.get(f"/api/v1/campaigns/{campaign.id}/adsets/new", headers=headers)
    assert form.status_code == 200, form.text
    assert form.json()["budgetAt"] == "adset"
    assert form.json()["groups"] == [{"externalId": "s_1", "name": "Guruh"}]

    started = client.post(
        f"/api/v1/campaigns/{campaign.id}/adsets",
        json={"name": "Yangi guruh", "dailyBudget": 12.5},
        headers=headers,
    )
    assert started.status_code == 202, started.text
    log = _pending(db, owner, ActionType.CREATE_ADSET)
    assert str(log.id) == started.json()["actionId"]

    assert additions.apply_new_group(db, log_id=str(log.id)) == "applied"

    sent = dict(fake.calls)["adset"]
    assert (sent.name, sent.campaign_id, sent.status) == (
        "Yangi guruh",
        "c_1",
        "PAUSED",
    )
    assert sent.daily_budget_minor == 1250
    assert (sent.bid_strategy, sent.bid_amount_minor) == ("COST_CAP", 90)
    assert sent.targeting["age_min"] == 25
    assert sent.attribution[0]["window_days"] == 1
    db.expire_all()
    assert db.get(ActionLog, log.id).status == ActionStatus.APPLIED
    assert db.get(ActionLog, log.id).dropped == {"interests": ["x"]}
    row = db.scalar(select(AdSet).where(AdSet.external_id == "as_new"))
    assert row is not None
    assert (row.delivery, row.daily_budget_minor) == ("paused", 1250)
    assert row.campaign_id == campaign.id


def test_a_group_under_a_campaign_budget_takes_no_money_of_its_own(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, owner, campaign = _signed_in(client, db)
    campaign.daily_budget_minor = 5000
    db.commit()
    path = f"/api/v1/campaigns/{campaign.id}/adsets"

    assert client.get(f"{path}/new", headers=headers).json()["budgetAt"] == "campaign"
    refused = client.post(path, json={"name": "G", "dailyBudget": 20}, headers=headers)
    assert refused.status_code >= 400
    assert refused.json()["code"] == "campaign_holds_budget"

    started = client.post(path, json={"name": "G"}, headers=headers)
    assert started.status_code == 202, started.text
    log = _pending(db, owner, ActionType.CREATE_ADSET)
    assert additions.apply_new_group(db, log_id=str(log.id)) == "applied"
    assert dict(fake.calls)["adset"].daily_budget_minor == 0


def test_a_group_with_a_budget_of_its_own_must_say_how_much(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, _owner, campaign = _signed_in(client, db)

    refused = client.post(
        f"/api/v1/campaigns/{campaign.id}/adsets", json={"name": "G"}, headers=headers
    )

    assert refused.json()["code"] == "group_budget_needed"


def test_a_lifetime_budget_is_not_mistaken_for_a_group_budget(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, _owner, campaign = _signed_in(client, db)
    campaign.adsets[0].daily_budget_minor = None
    db.commit()
    path = f"/api/v1/campaigns/{campaign.id}/adsets"

    assert client.get(f"{path}/new", headers=headers).json()["budgetAt"] == "lifetime"
    refused = client.post(path, json={"name": "G", "dailyBudget": 20}, headers=headers)

    assert refused.json()["code"] == "lifetime_budget_campaign"


def test_a_finished_campaign_takes_nothing_new(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, _owner, campaign = _signed_in(client, db)
    campaign.delivery = "finished"
    db.commit()

    refused = client.post(
        f"/api/v1/campaigns/{campaign.id}/adsets",
        json={"name": "G", "dailyBudget": 20},
        headers=headers,
    )

    assert refused.json()["code"] == "campaign_finished"


def test_a_new_advert_is_a_paused_copy_with_what_was_typed(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, owner, _campaign = _signed_in(client, db)

    form = client.get("/api/v1/campaigns/adsets/s_1/ads/new", headers=headers)
    assert form.status_code == 200, form.text
    assert form.json()["externalId"] == "a_1"
    assert form.json()["message"] == "Buyurtma bering"

    started = client.post(
        "/api/v1/campaigns/adsets/s_1/ads",
        json={"name": "Yangisi", "message": "Bugun chegirma"},
        headers=headers,
    )
    assert started.status_code == 202, started.text
    log = _pending(db, owner, ActionType.CREATE_AD)

    assert additions.apply_new_ad(db, log_id=str(log.id)) == "applied"

    made = dict(fake.calls)
    assert made["creative"]["story"]["link_data"]["message"] == "Bugun chegirma"
    assert made["creative"]["story"]["page_id"] == "page_1"
    assert made["ad"]["status"] == "PAUSED"
    assert made["ad"]["adset"].id == "s_1"
    db.expire_all()
    row = db.scalar(select(Ad).where(Ad.external_id == "ad_new"))
    assert row is not None
    assert (row.delivery, row.creative_external_id) == ("paused", "cr_new")


def test_an_empty_new_group_borrows_an_advert_from_its_campaign(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, owner, campaign = _signed_in(client, db)
    empty = AdSet(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="s_2",
        campaign_id=campaign.id,
        name="Bo'sh",
        delivery="paused",
        status="PAUSED",
        currency="USD",
        synced_at=utcnow(),
    )
    db.add(empty)
    db.commit()

    form = client.get("/api/v1/campaigns/adsets/s_2/ads/new", headers=headers)

    assert form.status_code == 200, form.text
    assert form.json()["externalId"] == "a_1"


def test_an_advert_that_runs_a_post_is_repeated_as_it_is(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    creative = db.scalar(select(AdCreative).where(AdCreative.external_id == "cr_1"))
    assert creative is not None
    creative.story_raw = {}
    db.commit()
    path = "/api/v1/campaigns/adsets/s_1/ads"

    assert client.get(f"{path}/new", headers=headers).json()["canSwap"] is False
    changed = client.post(path, json={"name": "Y", "message": "M"}, headers=headers)
    assert changed.json()["code"] == "creative_not_editable"

    started = client.post(path, json={"name": "Y"}, headers=headers)
    assert started.status_code == 202, started.text
    log = _pending(db, owner, ActionType.CREATE_AD)
    assert additions.apply_new_ad(db, log_id=str(log.id)) == "applied"

    made = dict(fake.calls)
    assert "creative" not in made
    assert made["ad"]["creative"].id == "cr_1"


def test_an_advert_meta_refuses_leaves_no_creative_behind(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    fake.refuse_ad = True
    client.post("/api/v1/campaigns/adsets/s_1/ads", json={"name": "Y"}, headers=headers)
    log = _pending(db, owner, ActionType.CREATE_AD)

    assert additions.apply_new_ad(db, log_id=str(log.id)) == "failed"

    assert fake.removed == ["cr_new"]
    db.expire_all()
    assert db.get(ActionLog, log.id).status == ActionStatus.FAILED
    assert db.scalar(select(Ad).where(Ad.external_id == "ad_new")) is None


def test_a_second_press_waits_for_the_first(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    headers, _owner, _campaign = _signed_in(client, db)
    path = "/api/v1/campaigns/adsets/s_1/ads"

    assert client.post(path, json={"name": "Y"}, headers=headers).status_code == 202
    second = client.post(path, json={"name": "Y"}, headers=headers)

    assert second.json()["code"] == "change_in_flight"


def test_a_campaign_budget_answers_for_the_groups_it_pays(
    client: TestClient, db: Session, queued: list, fake: Fake
) -> None:
    """Learning and the floor live on the group; a campaign holding the money
    must obey both, or the budget lock would vanish with the budget's move."""
    _headers, _owner, campaign = _signed_in(client, db)
    campaign.daily_budget_minor = 5000
    group = campaign.adsets[0]
    group.daily_budget_minor = None
    group.is_learning = True
    group.optimization_goal_raw = "LEAD_GENERATION"
    db.commit()

    controls = selectors.controls_for(target=campaign, level=ManagedLevel.CAMPAIGN)

    assert controls.can_budget is False
    assert controls.floor_minor == selectors.budget_floor(
        target=group, level=ManagedLevel.ADSET
    )
