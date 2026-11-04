"""The proposal editor's save refused: a 422 under the editor's own field names."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ads.constants import AD_LINE_MAX, PRIMARY_TEXT_MAX
from app.modules.ads.models import CampaignLaunch
from tests.pg.test_launch_api import _ready
from tests.pg.test_launch_proposal_patch import _reviewed, _variant


def _launch(client: TestClient, db: Session) -> tuple[CampaignLaunch, dict[str, str]]:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)
    variant = _variant(db, launch)
    variant.primary_text = "Yangi osh, chegirma bilan"
    db.commit()
    return launch, auth


def _save(
    client: TestClient, launch: CampaignLaunch, auth: dict[str, str], **ad: str
) -> dict:
    url = f"/api/v1/launch/drafts/{launch.id}/edit"
    edit = client.get(url, headers=auth).json()
    edit["ads"][0] |= ad
    saved = client.put(url, json=edit, headers=auth)
    return {**saved.json(), "code_": saved.status_code}


def test_a_headline_as_long_as_meta_takes_is_saved(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)

    saved = _save(
        client, launch, auth, headline="x" * AD_LINE_MAX, desc="y" * AD_LINE_MAX
    )

    assert saved["code_"] == 200, saved
    variant = _variant(db, launch)
    assert len(variant.headline) == len(variant.description) == AD_LINE_MAX


def test_a_line_too_long_is_refused_under_its_field_not_a_server_error(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)

    refused = _save(client, launch, auth, headline="x" * (AD_LINE_MAX + 1))

    assert refused["code_"] == 422, refused
    assert refused["problems"] == {
        "ads.0.headline": f"1-reklama: sarlavha {AD_LINE_MAX} belgidan oshmasin."
    }


def test_a_text_too_long_is_refused_under_the_advert_that_holds_it(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)

    refused = _save(client, launch, auth, text="x" * (PRIMARY_TEXT_MAX + 1))

    assert refused["code_"] == 422, refused
    assert list(refused["problems"]) == ["ads.0.text"]
    assert refused["problems"]["ads.0.text"].startswith("1-reklama:")


def test_a_goal_without_a_lead_form_saves_without_one(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)
    url = f"/api/v1/launch/drafts/{launch.id}/edit"
    edit = client.get(url, headers=auth).json()
    edit.pop("form")
    edit["ads"][0]["headline"] = "Bahor chegirmasi"

    saved = client.put(url, json=edit, headers=auth)

    assert saved.status_code == 200, saved.text
    assert _variant(db, launch).headline == "Bahor chegirmasi"
