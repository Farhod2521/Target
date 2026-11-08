"""The editor's «Kengaytirilgan» tab: each kind of campaign can be picked by name."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ads.constants import CAMPAIGN_TYPE, FREQUENCY_CAP
from app.modules.ads.models import CampaignLaunch
from tests.pg.test_launch_editor_save import _launch


def _calls(
    client: TestClient, db: Session
) -> tuple[CampaignLaunch, str, dict[str, str]]:
    launch, auth = _launch(client, db)
    launch.answers = {
        **launch.answers,
        "goal": "calls",
        "phone_number": "+998901234567",
        CAMPAIGN_TYPE: "calls_many",
    }
    db.commit()
    return launch, f"/api/v1/launch/drafts/{launch.id}/edit", auth


def _kind_row(edit: dict) -> dict:
    return next(row for row in edit["adv"] if row["key"] == "buying_type")


def test_the_three_call_kinds_are_told_apart_by_metas_word(
    client: TestClient, db: Session, queued: list
) -> None:
    _launch_row, url, auth = _calls(client, db)

    row = _kind_row(client.get(url, headers=auth).json())

    assert row["options"] == [
        "Qo'ng'iroqlar · Traffic",
        "Qo'ng'iroqlar · Engagement",
        "Qo'ng'iroqlar · Leads",
    ]
    assert row["value"] == "Qo'ng'iroqlar · Traffic"


def test_a_call_kind_picked_by_name_is_the_one_saved(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, url, auth = _calls(client, db)
    edit = client.get(url, headers=auth).json()
    _kind_row(edit)["value"] = "Qo'ng'iroqlar · Leads"

    saved = client.put(url, json=edit, headers=auth)

    assert saved.status_code == 200, saved.text
    db.refresh(launch)
    assert launch.answers[CAMPAIGN_TYPE] == "calls_ready"
    assert _kind_row(client.get(url, headers=auth).json())["value"] == (
        "Qo'ng'iroqlar · Leads"
    )


def test_a_kind_with_its_own_name_is_written_as_it_was(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)
    url = f"/api/v1/launch/drafts/{launch.id}/edit"

    row = _kind_row(client.get(url, headers=auth).json())

    assert "Havolani bosganlar" in row["options"]
    assert not any("·" in name for name in row["options"])


def test_quality_leads_are_neither_shown_nor_kept_where_not_offered(
    client: TestClient, db: Session, queued: list
) -> None:
    """Saved, it was bought on every request anyway: the account is not open to it."""
    launch, auth = _launch(client, db)
    url = f"/api/v1/launch/drafts/{launch.id}/edit"
    edit = client.get(url, headers=auth).json()
    assert edit["aud"]["optimizeOffered"] is False
    edit["aud"]["optimize"] = "quality"

    saved = client.put(url, json=edit, headers=auth)

    assert saved.status_code == 200, saved.text
    db.refresh(launch)
    assert launch.buy_qualified_leads is False


def _reach(
    client: TestClient, db: Session
) -> tuple[CampaignLaunch, str, dict[str, str]]:
    launch, auth = _launch(client, db)
    launch.answers = {
        **launch.answers,
        "goal": "views",
        CAMPAIGN_TYPE: "seen_widely",
        FREQUENCY_CAP: [],
    }
    db.commit()
    return launch, f"/api/v1/launch/drafts/{launch.id}/edit", auth


def _row(edit: dict, key: str) -> dict | None:
    return next((row for row in edit["adv"] if row["key"] == key), None)


def test_the_reach_cap_is_picked_and_dropped_in_the_tab(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, url, auth = _reach(client, db)
    edit = client.get(url, headers=auth).json()
    row = _row(edit, "frequency")
    assert row is not None and row["mode"] == ""
    assert row["value"] == "Meta o'zi belgilaydi"
    assert "7 kunda 2 martagacha" in row["options"]
    row["value"] = "7 kunda 2 martagacha"

    saved = client.put(url, json=edit, headers=auth)

    assert saved.status_code == 200, saved.text
    db.refresh(launch)
    assert launch.answers[FREQUENCY_CAP] == [2, 7]

    edit = client.get(url, headers=auth).json()
    row = _row(edit, "frequency")
    assert row is not None and row["value"] == "7 kunda 2 martagacha"
    row["value"] = "Meta o'zi belgilaydi"
    assert client.put(url, json=edit, headers=auth).status_code == 200
    db.refresh(launch)
    assert launch.answers[FREQUENCY_CAP] == []


def test_a_goal_meta_caps_no_frequency_on_has_no_cap_row(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)

    edit = client.get(f"/api/v1/launch/drafts/{launch.id}/edit", headers=auth).json()

    assert _row(edit, "frequency") is None
