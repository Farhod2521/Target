"""The editor's «Kengaytirilgan» tab: each kind of campaign can be picked by name."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ads.constants import CAMPAIGN_TYPE
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
