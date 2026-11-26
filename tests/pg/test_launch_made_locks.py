"""A launch already at Meta is not prepared again, and ids Meta no longer has
stop locking a launch still in preparation.

The incident: a launch created on 07.11 had its plan saved again with another
goal. The answers reset it to a draft, the proposal was rebuilt to ready, and
the ids of the long-deleted campaign stayed - so it could neither be edited,
started nor thrown away.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import DraftSection, LaunchStatus
from app.modules.ads.exceptions import ProposalLocked
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.services import mirror
from app.modules.ads.services.launch import is_discardable, save_answers
from app.modules.ads.services.launch_refs import release_launch_refs
from app.modules.integrations.constants import ConnectionStatus
from tests.pg.test_launch_api import _ready
from tests.pg.test_light_mirror import Meta, _counts, _wired
from tests.pg.test_sweep_accounts import _account

REFS: dict[str, Any] = {
    "campaign": "120",
    "adset": ["121"],
    "ad": ["122"],
    "creative": ["123"],
}


def _planned(client: TestClient, db: Session) -> tuple[dict[str, str], CampaignLaunch]:
    """A launch whose plan is saved and whose proposal is written."""
    auth, _user = _ready(client, db)
    launch_id = client.post("/api/v1/launch", headers=auth).json()["id"]
    goals = [
        item["goal"]
        for item in client.get(f"/api/v1/launch/{launch_id}/plan", headers=auth).json()[
            "goals"
        ]
    ]
    goal = "traffic" if "traffic" in goals else goals[0]
    saved = client.post(
        f"/api/v1/launch/{launch_id}/plan", json=_plan(goal), headers=auth
    )
    assert saved.status_code == 200, saved.text
    launch = db.get(CampaignLaunch, launch_id)
    assert launch is not None
    draft = draft_field.empty_draft()
    draft[DraftSection.AUDIENCE] = {"ai": {"age_min": 18}, "chosen": None}
    launch.draft = draft
    db.commit()
    assert draft_field.is_written(launch.draft)
    return auth, launch


def _plan(goal: str) -> dict[str, str]:
    return {
        "goal": goal,
        "daily_budget": "10",
        "link_url": "bahor.example",
        "phone_number": "+998901234567",
        "welcome_text": "Salom!",
        "start_day": "tomorrow",
    }


def _made(db: Session, launch: CampaignLaunch, status: LaunchStatus) -> None:
    launch.status = str(status)
    launch.created_refs = dict(REFS)
    db.commit()


def _other_goal(launch: CampaignLaunch) -> str:
    return "messages" if launch.answers["goal"] != "messages" else "traffic"


# --- A made launch is history ---------------------------------------------
def test_a_created_launch_refuses_a_new_plan(client: TestClient, db: Session) -> None:
    auth, launch = _planned(client, db)
    goal = launch.answers["goal"]
    _made(db, launch, LaunchStatus.CREATED)

    refused = client.post(
        f"/api/v1/launch/{launch.id}/plan",
        json=_plan(_other_goal(launch)),
        headers=auth,
    )

    assert refused.json()["code"] == "proposal_locked", refused.text
    db.refresh(launch)
    assert launch.status == LaunchStatus.CREATED
    assert launch.answers["goal"] == goal
    assert launch.created_refs == REFS


def test_a_created_launch_is_not_prepared_again(
    client: TestClient, db: Session
) -> None:
    auth, launch = _planned(client, db)
    _made(db, launch, LaunchStatus.CREATED)

    refused = client.post(f"/api/v1/launch/{launch.id}/retry", headers=auth)

    assert refused.json()["refusal"] == ProposalLocked().message, refused.text
    db.refresh(launch)
    assert launch.status == LaunchStatus.CREATED


def test_a_launch_being_created_takes_no_answers(
    client: TestClient, db: Session
) -> None:
    _auth, launch = _planned(client, db)
    _made(db, launch, LaunchStatus.CREATING)

    with pytest.raises(ProposalLocked):
        save_answers(db, launch=launch, daily_budget_minor=2_000)


# --- A failed launch keeps its campaign for the retry -----------------------
def test_a_failed_launch_with_its_campaign_cannot_start_over(
    client: TestClient, db: Session
) -> None:
    _auth, launch = _planned(client, db)
    _made(db, launch, LaunchStatus.FAILED)

    with pytest.raises(ProposalLocked):
        save_answers(db, launch=launch, goal=_other_goal(launch))


def test_a_failed_launch_with_its_campaign_can_still_be_fixed(
    client: TestClient, db: Session
) -> None:
    """What the retry needs - a budget, a picture - stays open."""
    _auth, launch = _planned(client, db)
    _made(db, launch, LaunchStatus.FAILED)

    save_answers(db, launch=launch, daily_budget_minor=2_000)

    assert launch.daily_budget_minor == 2_000
    assert launch.status == LaunchStatus.FAILED


# --- Ids Meta no longer has ---------------------------------------------------
def test_ids_gone_at_meta_free_a_failed_launch(client: TestClient, db: Session) -> None:
    _auth, launch = _planned(client, db)
    _made(db, launch, LaunchStatus.FAILED)
    assert not is_discardable(db, launch=launch)

    for step, ids in (("ad", ["122"]), ("adset", ["121"]), ("campaign", ["120"])):
        release_launch_refs(db, step=step, external_ids=ids)
    db.commit()

    db.refresh(launch)
    assert launch.created_refs == {"creative": ["123"]}
    assert is_discardable(db, launch=launch)


def test_a_created_launch_keeps_its_ids_as_its_record(
    client: TestClient, db: Session
) -> None:
    _auth, launch = _planned(client, db)
    _made(db, launch, LaunchStatus.CREATED)

    released = release_launch_refs(db, step="campaign", external_ids=["120"])
    db.commit()

    db.refresh(launch)
    assert released == 0
    assert launch.created_refs == REFS


def test_a_campaign_gone_from_meta_frees_the_failed_launch_holding_it(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the sync itself: the row goes, and so does the launch's id."""
    account = _account(db, 71, status=ConnectionStatus.ACTIVE)
    port = Meta(old_ads=1)
    _wired(monkeypatch, port)
    mirror.sync_ad_account(db, ad_account=account, whole=True)
    assert _counts(db) == (2, 2, 2)
    held = {"campaign": "c_old", "adset": ["s_old"], "ad": ["a_old_0"]}
    failed = CampaignLaunch(
        owner_id=account.owner_id,
        ad_account_id=account.id,
        status=str(LaunchStatus.FAILED),
        created_refs=dict(held),
    )
    made = CampaignLaunch(
        owner_id=account.owner_id,
        ad_account_id=account.id,
        status=str(LaunchStatus.CREATED),
        created_refs=dict(held),
    )
    db.add_all([failed, made])
    db.commit()
    port.campaigns = [row for row in port.campaigns if row.ref.id != "c_old"]
    port.adsets = [row for row in port.adsets if row.campaign_ref.id != "c_old"]
    port.ads = [row for row in port.ads if row.adset_ref.id != "s_old"]

    mirror.sync_ad_account(db, ad_account=account, whole=True)

    db.refresh(failed)
    db.refresh(made)
    assert failed.created_refs == {}
    assert made.created_refs == held
