"""One switch for a campaign and its one group; each group its own among several.

What «Yoqish» and «To'xtatish» reach, wherever they are pressed: the campaigns
screen, the chat, an undo, the guard, a lapse.
"""

import pytest
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import actions, selectors
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.exceptions import AlreadyInState
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
from app.modules.ads.selectors.delivery import (
    ADS_OFF,
    ALL_GROUPS_OFF,
    CAMPAIGN_ADS_OFF,
)
from app.modules.ads.services.manage import _landed
from app.modules.audit.constants import ActionType, ActorType
from app.modules.audit.models import ActionLog
from tests.pg.test_ads_manage import _mirror, _owner_with_account


@pytest.fixture(autouse=True)
def _paid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.billing.services.require_live_subscription", lambda *_a, **_k: None
    )


def _group(
    db: Session, owner: User, campaign: Campaign, ref: str, **state: str
) -> AdSet:
    row = AdSet(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=ref,
        campaign_id=campaign.id,
        name=f"Guruh {ref}",
        delivery=state.get("delivery", "active"),
        status=state.get("status", "ACTIVE"),
        synced_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _advert(db: Session, owner: User, group: AdSet, ref: str, **state: str) -> Ad:
    row = Ad(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=ref,
        adset_id=group.id,
        name=f"Reklama {ref}",
        delivery=state.get("delivery", "active"),
        status=state.get("status", "ACTIVE"),
        synced_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _off(row: object, delivery: str = "paused") -> None:
    row.delivery, row.status = delivery, "PAUSED"  # type: ignore[attr-defined]


def _agent_paused(db: Session, owner: User, level: str, ref: str) -> None:
    db.add(
        ActionLog(
            owner_id=owner.id,
            action=ActionType.PAUSE,
            actor_type=ActorType.AGENT,
            target_level=level,
            target_external_id=ref,
            target_provider=PROVIDER,
            idempotency_key=f"agent-{ref}",
            status="applied",
        )
    )


def _plan(db: Session, owner: User, campaign: Campaign) -> selectors.ResumePlan:
    db.expire_all()
    campaign = db.get(Campaign, campaign.id)
    return selectors.resume_plan(
        db, owner=owner, target=campaign, level=ManagedLevel.CAMPAIGN
    )


def _opened(db: Session) -> list[tuple[str, str, str]]:
    return [
        (log.action, log.target_level, log.target_external_id)
        for log in db.scalars(select(ActionLog).where(ActionLog.status == "pending"))
    ]


# -- one group: one switch ----------------------------------------------------------


def test_a_campaign_on_with_its_one_group_stopped_by_the_agent_starts_it(
    db: Session,
) -> None:
    """The bug: the agent stopped the hidden group, and «Yoqish» left it off."""
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    group = db.scalars(select(AdSet)).one()
    _off(group)
    db.scalars(select(Ad)).one().delivery = "paused_above"
    _agent_paused(db, owner, "adset", "s_1")
    db.commit()

    assert _plan(db, owner, campaign).targets == [
        ("campaign", "c_1"),
        ("adset", "s_1"),
    ]
    log = actions.request(
        db,
        user=owner,
        ask=actions.Resume(level=ManagedLevel.CAMPAIGN, external_id="c_1"),
    )
    db.commit()
    assert (log.target_level, log.target_external_id) == ("adset", "s_1")
    assert _opened(db) == [("resume", "adset", "s_1")]


def test_both_off_both_start(db: Session) -> None:
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    _off(campaign)
    _off(db.scalars(select(AdSet)).one())
    db.commit()

    actions.request(
        db,
        user=owner,
        ask=actions.Resume(level=ManagedLevel.CAMPAIGN, external_id="c_1"),
    )
    db.commit()
    assert sorted(_opened(db)) == [
        ("resume", "adset", "s_1"),
        ("resume", "campaign", "c_1"),
    ]


def test_stopping_the_one_group_stops_its_campaign(db: Session) -> None:
    owner, account = _owner_with_account(db)
    _mirror(db, owner, account.id)

    log = actions.request(
        db, user=owner, ask=actions.Pause(level=ManagedLevel.ADSET, external_id="s_1")
    )
    db.commit()
    assert (log.target_level, log.target_external_id) == ("campaign", "c_1")


def test_the_one_group_under_a_stopped_campaign_offers_no_stop(db: Session) -> None:
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    _off(campaign)
    group = db.scalars(select(AdSet)).one()
    group.delivery = "paused_above"
    db.commit()

    assert selectors.controls_for(target=group, level="adset").can_pause is False
    with pytest.raises(AlreadyInState):
        actions.request(
            db,
            user=owner,
            ask=actions.Pause(level=ManagedLevel.ADSET, external_id="s_1"),
        )


def test_a_start_asked_of_a_group_under_a_stopped_campaign_starts_the_campaign(
    db: Session,
) -> None:
    """The chat's and the guard's «Qayta yoqish»: the group's own switch is on."""
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    _off(campaign)
    db.scalars(select(AdSet)).one().delivery = "paused_above"
    db.commit()

    planned = actions.preview(
        db, user=owner, ask=actions.Resume(level=ManagedLevel.ADSET, external_id="s_1")
    )
    assert (planned.level, planned.external_id) == ("campaign", "c_1")
    log = actions.request(
        db, user=owner, ask=actions.Resume(level=ManagedLevel.ADSET, external_id="s_1")
    )
    db.commit()
    assert (log.target_level, log.target_external_id) == ("campaign", "c_1")
    assert _opened(db) == [("resume", "campaign", "c_1")]


def test_an_undo_of_the_campaign_stop_starts_its_one_group_too(db: Session) -> None:
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    _off(campaign)
    _off(db.scalars(select(AdSet)).one())
    stop = ActionLog(
        owner_id=owner.id,
        action=ActionType.PAUSE,
        target_level="campaign",
        target_external_id="c_1",
        target_provider=PROVIDER,
        idempotency_key="stop",
        status="applied",
        previous_state={"delivery": "active"},
    )
    db.add(stop)
    db.commit()

    actions.revert(db, user=owner, log_id=str(stop.id))
    db.commit()
    assert sorted(_opened(db)) == [
        ("resume", "adset", "s_1"),
        ("resume", "campaign", "c_1"),
    ]


# -- several groups: each its own --------------------------------------------------


def test_among_several_groups_a_stopped_one_stays_off_even_when_all_are(
    db: Session,
) -> None:
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    _off(campaign)
    _off(db.scalars(select(AdSet)).one())
    _group(db, owner, campaign, "s_2", delivery="paused", status="PAUSED")
    db.commit()

    plan = _plan(db, owner, campaign)
    assert plan.targets == [("campaign", "c_1")]
    assert plan.notes == [ALL_GROUPS_OFF]


def test_among_several_groups_stopping_one_stops_only_it(db: Session) -> None:
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    _group(db, owner, campaign, "s_2")
    db.commit()

    log = actions.request(
        db, user=owner, ask=actions.Pause(level=ManagedLevel.ADSET, external_id="s_1")
    )
    db.commit()
    assert (log.target_level, log.target_external_id) == ("adset", "s_1")


def test_a_group_a_launch_never_started_goes_on_with_the_campaign(
    db: Session,
) -> None:
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    _off(campaign)
    fresh = _group(db, owner, campaign, "s_2", delivery="paused", status="PAUSED")
    _advert(db, owner, fresh, "a_2", delivery="paused", status="PAUSED")
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            provider=PROVIDER,
            status="created",
            created_refs={"campaign": "c_1", "adset": ["s_2"], "ad": ["a_2"]},
        )
    )
    db.commit()

    assert _plan(db, owner, campaign).targets == [
        ("campaign", "c_1"),
        ("adset", "s_2"),
        ("ad", "a_2"),
    ]


# -- adverts ----------------------------------------------------------------------


def test_a_group_with_one_advert_starts_it_and_several_are_the_owners(
    db: Session,
) -> None:
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    group = db.scalars(select(AdSet)).one()
    _off(group)
    _off(db.scalars(select(Ad)).one())
    db.commit()
    assert _plan(db, owner, campaign).targets == [
        ("campaign", "c_1"),
        ("adset", "s_1"),
        ("ad", "a_1"),
    ]

    _advert(db, owner, group, "a_2", delivery="paused", status="PAUSED")
    db.commit()
    plan = _plan(db, owner, campaign)
    assert plan.targets == [("campaign", "c_1"), ("adset", "s_1")]
    assert plan.notes == [CAMPAIGN_ADS_OFF]
    adset_plan = selectors.resume_plan(
        db, owner=owner, target=db.get(AdSet, group.id), level=ManagedLevel.ADSET
    )
    assert adset_plan.notes == [ADS_OFF.format(name="Guruh")]


def test_ads_are_counted_in_their_own_group(db: Session) -> None:
    """One group's running advert does not keep another group's lone one off."""
    owner, account = _owner_with_account(db)
    campaign = _mirror(db, owner, account.id)
    other = _group(db, owner, campaign, "s_2")
    _advert(db, owner, other, "a_2", delivery="paused", status="PAUSED")
    db.commit()

    assert _plan(db, owner, campaign).targets == [
        ("campaign", "c_1"),
        ("ad", "a_2"),
    ]


# -- faults keep their switch ------------------------------------------------------


def test_a_faulted_row_still_has_its_switch(db: Session) -> None:
    owner, account = _owner_with_account(db)
    _mirror(db, owner, account.id)
    ad = db.scalars(select(Ad)).one()
    ad.delivery, ad.status, ad.issue_codes = "rejected", "PAUSED", ["1"]
    db.commit()
    controls = selectors.controls_for(target=ad, level="ad")
    assert (controls.can_resume, controls.can_pause) == (True, False)

    ad.status = "ACTIVE"
    db.commit()
    controls = selectors.controls_for(target=ad, level="ad")
    assert (controls.can_resume, controls.can_pause) == (False, True)


def test_a_switch_is_judged_by_its_own_switch() -> None:
    from adskit import ExternalRef
    from adskit.dto import StatusDTO

    def after(status: str, delivery: str) -> StatusDTO:
        return StatusDTO(
            ref=ExternalRef(provider=PROVIDER, level="adset", id="s_1"),
            status=status,
            effective_status="",
            delivery=delivery,
        )

    resume = ActionLog(action=ActionType.RESUME)
    pause = ActionLog(action=ActionType.PAUSE)
    assert _landed(log=resume, after=after("ACTIVE", "paused_above")) is True
    assert _landed(log=resume, after=after("PAUSED", "paused")) is False
    assert _landed(log=pause, after=after("PAUSED", "rejected")) is True
    assert _landed(log=pause, after=after("", "paused")) is True


# -- the screen says what it left off ------------------------------------------------


def test_the_screens_start_says_what_it_left_off(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    from tests.pg.conftest import sign_up
    from tests.pg.test_cabinet_flows import _cabinet

    headers = sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    campaign = _mirror(db, owner, account.id)
    _off(campaign)
    _off(db.scalars(select(AdSet)).one())
    _group(db, owner, campaign, "s_2", delivery="paused", status="PAUSED")
    db.commit()

    state = client.post(
        "/api/v1/campaigns/manage/campaign/c_1/resume", headers=headers
    ).json()
    assert state["refused"] is None
    assert state["notes"] == [ALL_GROUPS_OFF]


def test_a_stop_made_on_the_campaign_is_found_by_its_group(db: Session) -> None:
    """The auto-stop counts from its last stop: under the campaign it is found by
    the group, or the group would be stopped again for what was spent before."""
    from app.modules.agent.constants import AUTO_STOP_MARK
    from app.modules.agent.selectors.stopped_watch import last_stops

    owner, account = _owner_with_account(db)
    _mirror(db, owner, account.id)
    log = actions.request(
        db, user=owner, ask=actions.Pause(level=ManagedLevel.ADSET, external_id="s_1")
    )
    log.request_payload = {**log.request_payload, AUTO_STOP_MARK: {"spend_minor": 5}}
    db.commit()

    assert log.request_payload["for_adset"] == "s_1"
    assert last_stops(db, owner=owner, adset_ids=["s_1"]) == {"s_1": log}
