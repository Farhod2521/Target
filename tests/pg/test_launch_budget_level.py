"""Who holds a launch's daily budget, from the editor to what goes to Meta."""

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from metaads.specs import AdSetSpec, CampaignSpec
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.constants import BUDGET_LEVEL, BUDGET_SHARING
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.ad_groups import underfunded
from app.modules.ads.selectors.budget_level import campaign_budget_minor
from app.modules.ads.services import meta_specs
from app.modules.businesses.models import Business
from tests.pg.test_launch_api import _ready
from tests.pg.test_launch_proposal_patch import _reviewed

BUILT: Any = SimpleNamespace(
    objective="OUTCOME_TRAFFIC",
    special_ad_categories=(),
    special_ad_category_countries=(),
    max_result_cost_minor=0,
    optimization_goal="LINK_CLICKS",
    billing_event="IMPRESSIONS",
    destination_type="",
    promoted_object={},
    attribution_days=None,
    frequency_cap=None,
)


def _specs(db: Session, launch: CampaignLaunch) -> tuple[CampaignSpec, AdSetSpec]:
    business = db.scalar(select(Business).where(Business.user_id == launch.owner_id))
    assert business is not None
    return (
        meta_specs.goal_campaign_spec(
            launch=launch, business=business, built=BUILT, number=1
        ),
        meta_specs.adset_spec(
            launch=launch, business=business, built=BUILT, campaign_id="c", name="g"
        ),
    )


def _edit(client: TestClient, launch: CampaignLaunch, auth: dict[str, str]) -> dict:
    shown = client.get(f"/api/v1/launch/drafts/{launch.id}/edit", headers=auth)
    assert shown.status_code == 200, shown.text
    return shown.json()


def _save(
    client: TestClient,
    db: Session,
    launch: CampaignLaunch,
    auth: dict[str, str],
    budget: dict,
) -> None:
    edit = _edit(client, launch, auth)
    saved = client.put(
        f"/api/v1/launch/drafts/{launch.id}/edit",
        json=edit | {"budget": budget},
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    db.expire_all()
    db.refresh(launch)


def test_left_alone_the_campaign_holds_the_budget(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)

    assert _edit(client, launch, auth)["budget"] == {
        "level": "campaign",
        "sharing": False,
        "locked": False,
    }
    campaign, adset = _specs(db, launch)
    assert campaign.daily_budget_minor == launch.daily_budget_minor > 0
    assert campaign.bid_strategy == "LOWEST_COST_WITHOUT_CAP"
    assert adset.daily_budget_minor == 0


def test_the_owner_moves_it_to_the_groups_with_sharing_and_back(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)

    _save(client, db, launch, auth, {"level": "adset", "sharing": True})

    assert launch.answers[BUDGET_LEVEL] == "adset"
    assert launch.answers[BUDGET_SHARING] is True
    campaign, adset = _specs(db, launch)
    assert campaign.daily_budget_minor == 0
    assert campaign.budget_sharing is True
    assert campaign.bid_strategy == "LOWEST_COST_WITHOUT_CAP"
    assert adset.daily_budget_minor == launch.daily_budget_minor

    _save(client, db, launch, auth, {"level": "campaign", "sharing": False})

    assert campaign_budget_minor(launch=launch) == launch.daily_budget_minor
    assert _specs(db, launch)[0].budget_sharing is False


def test_sharing_cannot_stand_beside_a_campaign_budget(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)
    edit = _edit(client, launch, auth)

    refused = client.put(
        f"/api/v1/launch/drafts/{launch.id}/edit",
        json=edit | {"budget": {"level": "campaign", "sharing": True}},
        headers=auth,
    )

    assert refused.status_code >= 400
    db.expire_all()
    assert BUDGET_SHARING not in (db.get(CampaignLaunch, launch.id).answers or {})


def test_a_draft_already_divided_stays_with_its_groups(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)
    groups = [
        {"name": "A", "daily_budget_minor": 700},
        {"name": "B", "daily_budget_minor": 300},
    ]
    launch.ad_groups = groups
    db.commit()

    assert _edit(client, launch, auth)["budget"]["level"] == "adset"
    assert underfunded(db, launch=launch, floor_minor=800) is not None


def test_a_group_below_the_floor_is_no_matter_when_the_campaign_pays(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)
    _save(client, db, launch, auth, {"level": "campaign", "sharing": False})

    assert underfunded(db, launch=launch, floor_minor=10**9) is None


def test_a_launch_made_can_no_longer_move_it(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)
    edit = _edit(client, launch, auth)
    launch.status = "created"
    db.commit()

    refused = client.post(
        f"/api/v1/launch/{launch.id}/edit",
        json={"budget": {"level": "adset"}},
        headers=auth,
    )

    assert refused.status_code >= 400
    assert edit["budget"]["locked"] is False
