"""A running group's price ceiling, attribution window and frequency cap, against PostgreSQL."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from metaads.delivery import Delivery
from metaads.launcher import MetaLauncher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.actions import undoing
from app.modules.ads.models import AdSet
from app.modules.ads.services import delivery
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from tests.pg.test_ads_additions import (
    Fake,
    _pending,
    _signed_in,
    fake,  # noqa: F401
)

URL = "/api/v1/campaigns/adsets/s_1/delivery"


def _goal(db: Session, goal: str, **held: Any) -> AdSet:
    group = db.scalars(select(AdSet)).one()
    group.optimization_goal_raw = goal
    for key, value in held.items():
        setattr(group, key, value)
    db.commit()
    return group


def _holds(
    monkeypatch: pytest.MonkeyPatch, now: Delivery, readable: bool = True
) -> None:
    monkeypatch.setattr(delivery, "_read", lambda _group: (now, readable))


def test_a_lead_group_is_offered_a_ceiling_and_nothing_it_cannot_take(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _owner, _campaign = _signed_in(client, db)
    _goal(db, "LEAD_GENERATION")
    _holds(monkeypatch, Delivery(cap_minor=250))

    form = client.get(URL, headers=headers).json()

    assert form["readable"] is True and form["canChange"] is True
    assert form["costCap"] == {
        "offered": True,
        "value": 2.5,
        "highest": 3.33,
        "budgetMultiple": 3,
        "note": "",
    }
    assert form["attribution"]["offered"] is False
    assert form["frequency"]["offered"] is False


def test_a_site_goal_is_offered_its_window_and_a_reach_goal_its_cap(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _owner, _campaign = _signed_in(client, db)
    _goal(db, "OFFSITE_CONVERSIONS")
    _holds(monkeypatch, Delivery(window=(1, 1)))
    site = client.get(URL, headers=headers).json()
    _goal(db, "REACH")
    _holds(monkeypatch, Delivery(frequency=(2, 7)))
    reach = client.get(URL, headers=headers).json()

    assert site["attribution"]["value"] == "click_1_view_1"
    assert site["attribution"]["options"][0]["key"] == "click_7_view_1"
    assert all(row["label"] for row in site["attribution"]["options"])
    assert reach["frequency"] == {
        "offered": True,
        "times": 2,
        "days": 7,
        "maxTimes": 50,
        "maxDays": 90,
    }
    assert reach["costCap"]["offered"] is False


def test_what_meta_did_not_answer_is_said_and_not_drawn_as_empty(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _owner, _campaign = _signed_in(client, db)
    _goal(db, "LEAD_GENERATION")
    _holds(monkeypatch, Delivery(), readable=False)

    form = client.get(URL, headers=headers).json()
    refused = client.post(URL, json={"costCap": 2}, headers=headers)

    assert form["readable"] is False and form["canChange"] is False
    assert "hozir bermadi" in form["note"]
    assert (
        refused.status_code == 400 and refused.json()["code"] == "delivery_unreadable"
    )


def test_a_budget_held_by_the_campaign_and_a_bid_cap_close_the_ceiling(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _owner, _campaign = _signed_in(client, db)
    _goal(db, "LEAD_GENERATION", daily_budget_minor=None)
    _holds(monkeypatch, Delivery())
    shared = client.get(URL, headers=headers).json()["costCap"]
    _goal(db, "LEAD_GENERATION", daily_budget_minor=1000)
    _holds(monkeypatch, Delivery(foreign_bid="LOWEST_COST_WITH_BID_CAP"))
    foreign = client.get(URL, headers=headers).json()["costCap"]

    assert shared["offered"] is False and "kampaniyada" in shared["note"]
    assert foreign["offered"] is False and "Ads Manager" in foreign["note"]


def test_a_ceiling_is_set_changed_and_taken_off(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _goal(db, "LEAD_GENERATION")
    _holds(monkeypatch, Delivery(cap_minor=250))

    same = client.post(URL, json={"costCap": 2.5}, headers=headers)
    high = client.post(URL, json={"costCap": 5}, headers=headers)
    saved = client.post(URL, json={"costCap": None}, headers=headers)

    assert same.status_code == 400 and same.json()["code"] == "nothing_changed"
    assert high.status_code == 400 and high.json()["code"] == "cost_cap_too_low"
    assert saved.status_code == 200, saved.text
    log = _pending(db, owner, ActionType.DELIVERY_SET)
    assert log.request_payload["cap_minor"] == 0
    assert log.previous_state["delivery"] == {"cap_minor": 250}
    assert queued[-1][0].endswith("apply_delivery_task")
    assert delivery.fields_for(log) == {"bid_strategy": "LOWEST_COST_WITHOUT_CAP"}


def test_a_setting_the_goal_does_not_take_is_refused(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _owner, _campaign = _signed_in(client, db)
    _goal(db, "LINK_CLICKS")
    _holds(monkeypatch, Delivery())

    cap = client.post(URL, json={"costCap": 1}, headers=headers)
    window = client.post(URL, json={"attribution": "click_7"}, headers=headers)
    often = client.post(
        URL, json={"frequency": {"times": 2, "days": 7}}, headers=headers
    )

    assert cap.json()["code"] == "cost_cap_not_offered"
    assert window.json()["code"] == "delivery_option_unusable"
    assert often.json()["code"] == "delivery_option_unusable"


def test_a_window_and_a_frequency_cap_are_changed(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _goal(db, "OFFSITE_CONVERSIONS")
    _holds(monkeypatch, Delivery())

    unknown = client.post(URL, json={"attribution": "click_30"}, headers=headers)
    default = client.post(URL, json={"attribution": "click_7"}, headers=headers)
    saved = client.post(URL, json={"attribution": "click_1_view_1"}, headers=headers)

    assert unknown.json()["code"] == "delivery_option_unusable"
    # No window held is Meta's own default, so naming it changes nothing.
    assert default.json()["code"] == "nothing_changed"
    assert saved.status_code == 200, saved.text
    log = _pending(db, owner, ActionType.DELIVERY_SET)
    assert delivery.fields_for(log) == {
        "attribution_spec": [
            {"event_type": "CLICK_THROUGH", "window_days": 1},
            {"event_type": "VIEW_THROUGH", "window_days": 1},
        ]
    }


def test_a_frequency_cap_out_of_bounds_is_refused_and_one_is_taken_off(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _goal(db, "REACH")
    _holds(monkeypatch, Delivery(frequency=(2, 7)))

    wide = client.post(
        URL, json={"frequency": {"times": 2, "days": 91}}, headers=headers
    )
    often = client.post(
        URL, json={"frequency": {"times": 51, "days": 7}}, headers=headers
    )
    saved = client.post(URL, json={"frequency": None}, headers=headers)

    assert wide.json()["code"] == "delivery_option_unusable"
    assert often.json()["code"] == "delivery_option_unusable"
    assert saved.status_code == 200, saved.text
    log = _pending(db, owner, ActionType.DELIVERY_SET)
    assert delivery.fields_for(log) == {"frequency_control_specs": []}
    assert log.previous_state["delivery"] == {"frequency": [2, 7]}


def test_a_finished_group_takes_no_change_and_a_learning_one_is_warned(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _owner, _campaign = _signed_in(client, db)
    _goal(db, "LEAD_GENERATION", is_learning=True)
    _holds(monkeypatch, Delivery())
    learning = client.get(URL, headers=headers).json()
    _goal(db, "LEAD_GENERATION", delivery="finished")
    finished = client.get(URL, headers=headers).json()
    refused = client.post(URL, json={"costCap": 2}, headers=headers)

    assert learning["warnsLearning"] is True and learning["canChange"] is True
    assert finished["canChange"] is False and finished["note"]
    assert refused.json()["code"] == "campaign_finished"


def test_the_write_reaches_meta_in_one_call_and_can_be_put_back(
    client: TestClient,
    db: Session,
    queued: list,
    fake: Fake,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _goal(db, "LEAD_GENERATION")
    _holds(monkeypatch, Delivery(cap_minor=250))
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        MetaLauncher,
        "set_adset_delivery",
        lambda _self, **kw: sent.append(kw) or True,
    )
    client.post(URL, json={"costCap": 3}, headers=headers)
    log = _pending(db, owner, ActionType.DELIVERY_SET)

    assert delivery.apply_delivery(db, log_id=str(log.id)) == "applied"

    assert [call["data"] for call in sent] == [
        {"bid_strategy": "COST_CAP", "bid_amount": 300}
    ]
    assert sent[0]["adset"].id == "s_1" and sent[0]["dry_run"] is False
    db.expire_all()
    done = db.get(ActionLog, log.id)
    assert done is not None and done.status == ActionStatus.APPLIED
    back = undoing(done)
    assert back is not None and dict(back.asked) == {"cap_minor": 250}
