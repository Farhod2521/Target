"""A group's and an advert's name, an end date taken off and a ceiling removed, against PostgreSQL."""

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from metaads import writes
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads import actions
from app.modules.ads.actions import undoing
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.services import manage
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from tests.pg.test_ads_editing import _patch, _signed_with_campaign

ENDS = datetime(2027, 1, 31, 18, 59, 59, tzinfo=UTC)


def _logs(db: Session, action: str) -> list[ActionLog]:
    return list(db.scalars(select(ActionLog).where(ActionLog.action == action)))


def test_a_group_and_an_advert_are_renamed_like_a_campaign(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, _campaign = _signed_with_campaign(client, db)

    group = client.post(
        "/api/v1/campaigns/manage/adset/s_1/name",
        json={"name": "  Toshkent   25-45 "},
        headers=headers,
    )
    advert = client.post(
        "/api/v1/campaigns/manage/ad/a_1/name",
        json={"name": "Video 1"},
        headers=headers,
    )

    assert group.status_code == 200, group.text
    assert advert.status_code == 200, advert.text
    asked = {
        (log.target_level, log.target_external_id): log
        for log in _logs(db, ActionType.NAME_SET)
    }
    assert asked[("adset", "s_1")].request_payload["name"] == "Toshkent 25-45"
    assert asked[("adset", "s_1")].previous_state["name"] == "Guruh"
    assert asked[("ad", "a_1")].request_payload["name"] == "Video 1"
    assert queued[-1][0].endswith("apply_change_task")


def test_an_empty_name_and_the_same_name_are_refused(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, _campaign = _signed_with_campaign(client, db)
    url = "/api/v1/campaigns/manage/adset/s_1/name"

    empty = client.post(url, json={"name": "  "}, headers=headers)
    same = client.post(url, json={"name": "Guruh"}, headers=headers)
    missing = client.post(
        "/api/v1/campaigns/manage/ad/nope/name", json={"name": "X"}, headers=headers
    )

    assert empty.status_code == 422 and "name" in empty.text
    assert same.status_code in (400, 409) and _logs(db, ActionType.NAME_SET) == []
    assert missing.status_code == 404


def test_a_groups_earlier_name_is_put_back_at_its_own_level(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, _campaign = _signed_with_campaign(client, db)
    client.post(
        "/api/v1/campaigns/manage/adset/s_1/name",
        json={"name": "Yangi"},
        headers=headers,
    )
    log = _logs(db, ActionType.NAME_SET)[0]
    log.status, log.dry_run = ActionStatus.APPLIED, False

    assert undoing(log) == actions.Rename(
        external_id="s_1", name="Guruh", restore=True, level="adset"
    )


def _ending(db: Session, **held: Any) -> AdSet:
    group = db.scalars(select(AdSet)).one()
    group.end_time = ENDS
    for key, value in held.items():
        setattr(group, key, value)
    db.commit()
    return group


def test_an_end_date_is_taken_off_only_when_the_form_says_so(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, campaign = _signed_with_campaign(client, db)
    _ending(db)
    url = f"/api/v1/campaigns/{campaign.id}"

    form = client.get(f"{url}/edit", headers=headers).json()
    silent = client.patch(url, json=_patch(campaign), headers=headers)
    kept = client.patch(
        url, json=_patch(campaign, endsAt=form["endsAt"]), headers=headers
    )
    cleared = client.patch(url, json=_patch(campaign, endsAt=None), headers=headers)

    assert form["endsAt"] is not None and form["endsAtRequired"] is False
    # An older form that does not send the field removes nothing.
    assert silent.status_code == 204 and kept.status_code == 204
    assert cleared.status_code == 200, cleared.text
    (log,) = _logs(db, ActionType.END_TIME_SET)
    assert log.request_payload["end_time"] == ""
    assert log.previous_state["end_time"] == ENDS.isoformat()


def test_a_lifetime_budget_cannot_lose_its_end(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, campaign = _signed_with_campaign(client, db)
    _ending(db, daily_budget_minor=None)
    url = f"/api/v1/campaigns/{campaign.id}"

    form = client.get(f"{url}/edit", headers=headers).json()
    refused = client.patch(url, json=_patch(campaign, endsAt=None), headers=headers)

    assert form["endsAtRequired"] is True
    assert refused.status_code == 422 and "tugash sanasiz" in refused.text
    assert _logs(db, ActionType.END_TIME_SET) == []


def test_taking_the_end_off_and_putting_it_back_are_each_others_undo(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, campaign = _signed_with_campaign(client, db)
    _ending(db)
    client.patch(
        f"/api/v1/campaigns/{campaign.id}",
        json=_patch(campaign, endsAt=None),
        headers=headers,
    )
    (log,) = _logs(db, ActionType.END_TIME_SET)
    log.status, log.dry_run = ActionStatus.APPLIED, False

    back = undoing(log)

    assert back == actions.EndTime(external_id="s_1", end_time=ENDS, level="adset")
    log.previous_state = {**log.previous_state, "end_time": ""}
    assert undoing(log) == actions.EndTime(
        external_id="s_1", end_time=None, level="adset"
    )


def test_a_ceiling_is_removed_where_there_is_one(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, campaign = _signed_with_campaign(client, db)
    campaign = db.get(Campaign, campaign.id)
    assert campaign is not None
    campaign.spend_cap_minor = 50000
    db.commit()
    url = f"/api/v1/campaigns/{campaign.id}"

    form = client.get(f"{url}/edit", headers=headers).json()
    silent = client.patch(url, json=_patch(campaign), headers=headers)
    removed = client.patch(url, json=_patch(campaign, limit=None), headers=headers)

    assert form["limit"] == 500.0
    assert silent.status_code == 204
    assert removed.status_code == 200, removed.text
    (log,) = _logs(db, ActionType.SPEND_CAP_SET)
    assert log.request_payload["spend_cap_minor"] == 0
    assert log.previous_state["spend_cap_minor"] == 50000


def test_no_ceiling_cannot_be_removed_and_another_network_keeps_its_own(
    client: TestClient, db: Session, queued: list
) -> None:
    import pytest

    from app.modules.accounts.models import User
    from app.modules.ads.exceptions import AlreadyInState, ChangeRefused

    _headers, campaign = _signed_with_campaign(client, db)
    owner = db.get(User, campaign.owner_id)
    assert owner is not None

    with pytest.raises(AlreadyInState):
        manage.plan_spend_cap(db, user=owner, external_id="c_1", spend_cap_minor=0)
    campaign = db.get(Campaign, campaign.id)
    assert campaign is not None
    campaign.spend_cap_minor, campaign.provider = 50000, "google"
    db.commit()
    with pytest.raises(ChangeRefused):
        manage.plan_spend_cap(db, user=owner, external_id="c_1", spend_cap_minor=0)


class _Graph:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def for_token(self, _token: str) -> "_Graph":
        return self

    def post(self, path: str, **data: Any) -> dict[str, Any]:
        self.posts.append((path, data))
        return {"success": True}


def test_meta_is_sent_its_own_words_for_no_end_and_no_ceiling() -> None:
    graph = _Graph()

    writes.set_end_time(
        object_id="s_1", end_time="", token="t", client=graph, dry_run=False
    )  # type: ignore[arg-type]
    writes.set_spend_cap(
        object_id="c_1", spend_cap_minor=0, token="t", client=graph, dry_run=False
    )  # type: ignore[arg-type]
    writes.set_spend_cap(
        object_id="c_1", spend_cap_minor=700, token="t", client=graph, dry_run=False
    )  # type: ignore[arg-type]

    assert [
        (path, {k: str(v) for k, v in data.items()}) for path, data in graph.posts
    ] == [
        ("s_1", {"end_time": "0"}),
        ("c_1", {"spend_cap": "922337203685478"}),
        ("c_1", {"spend_cap": "700"}),
    ]


def test_the_mirror_forgets_a_limit_that_was_taken_off(
    client: TestClient, db: Session, queued: list
) -> None:
    from adskit.dto import ActionResult, StatusDTO
    from adskit.refs import ExternalRef

    _headers, _campaign = _signed_with_campaign(client, db)
    group = _ending(db)
    ref = ExternalRef(provider=group.provider, level="adset", id="s_1")  # type: ignore[arg-type]
    after = StatusDTO(ref=ref, status="ACTIVE", delivery="active")
    log = ActionLog(action=ActionType.END_TIME_SET, request_payload={"end_time": ""})

    limit = manage._limit(
        log=log, result=ActionResult(ok=True, ref=ref, applied={"end_time": ""})
    )
    manage._refresh_mirror(target=group, after=after, applied_limit=limit)

    assert group.end_time is None
    assert db.scalars(select(Ad)).first() is not None
