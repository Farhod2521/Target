"""A new launch shows on Instagram alone when the page has it, else on Facebook."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import DraftSection
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.services.targeting import apply_placement
from tests.pg.test_launch_api import _ready


def _launch(client: TestClient, db: Session, *, instagram: str) -> CampaignLaunch:
    auth, _user = _ready(client, db)
    launch_id = client.post("/api/v1/launch", headers=auth).json()["id"]
    launch = db.get(CampaignLaunch, launch_id)
    assert launch is not None
    page = launch_page(db, launch=launch)
    assert page is not None
    page.instagram_user_id = instagram
    launch.answers = {**(launch.answers or {}), "goal": "leads"}
    launch.draft = draft_field.empty_draft()
    db.commit()
    return launch


def _placement(launch: CampaignLaunch) -> object:
    chosen = draft_field.chosen(launch.draft, DraftSection.AUDIENCE) or {}
    return chosen.get("placement_mode")


def test_a_page_with_instagram_starts_on_instagram_only(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db, instagram="ig_1")

    apply_placement(db, launch=launch)

    assert _placement(launch) == "instagram"


def test_a_page_without_instagram_starts_on_facebook_only(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db, instagram="")

    apply_placement(db, launch=launch)

    assert _placement(launch) == "facebook"


def test_the_owners_own_choice_is_never_replaced(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db, instagram="ig_1")
    draft = launch.draft
    draft_field.choose(draft, DraftSection.AUDIENCE, {"placement_mode": "facebook"})
    draft_field.set_source(draft, draft_field.PLACEMENT_MODE, draft_field.BY_OWNER)
    launch.draft = draft

    apply_placement(db, launch=launch)

    assert _placement(launch) == "facebook"
