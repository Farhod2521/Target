"""TZ 3: the pixel, its events with seven-day counts, custom conversions."""

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from metaads.dto import CustomConversionRow, PixelEventRow
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.constants import CONVERSION_EVENT, EVENT_FEW, EVENT_NOT_ARRIVING
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.routers.launch_common import launch_business
from app.modules.ads.selectors.conversion_event import (
    conversion_event_choices,
    effective_conversion_event,
)
from app.modules.ads.selectors.pixel import chosen_pixel
from app.modules.ads.services.advanced import choose_conversion_event
from app.modules.ads.services.targeting import apply_conversion_event, launch_answers
from app.modules.integrations.models import PixelAccount
from app.modules.integrations.services import sync
from tests.pg.test_launch_api import _ready


def _launch(client: TestClient, db: Session) -> CampaignLaunch:
    auth, _user = _ready(client, db)
    launch_id = client.post("/api/v1/launch", headers=auth).json()["id"]
    launch = db.get(CampaignLaunch, launch_id)
    assert launch is not None
    launch.answers = {**(launch.answers or {}), "goal": "site_leads"}
    db.commit()
    return launch


def _pixel(
    db: Session,
    launch: CampaignLaunch,
    external_id: str,
    *,
    events: list[dict[str, Any]],
    active: bool = False,
    conversions: list[dict[str, Any]] | None = None,
) -> PixelAccount:
    account = launch.ad_account
    assert account is not None
    pixel = PixelAccount(
        owner_id=launch.owner_id,
        provider=launch.provider,
        external_id=external_id,
        connection_id=account.connection_id,
        ad_account_id=account.id,
        name=f"Pixel {external_id}",
        is_active=active,
        recent_events=events,
        events_synced_at=utcnow(),
        conversions=conversions or [],
    )
    db.add(pixel)
    db.commit()
    return pixel


def test_the_pixel_that_sent_most_in_seven_days_is_chosen(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db)
    _pixel(db, launch, "1", events=[{"event": "Lead", "count": 3}], active=True)
    _pixel(db, launch, "2", events=[{"event": "PageView", "count": 900}])

    found = chosen_pixel(db, launch=launch)

    assert found is not None and found.external_id == "2"


def test_the_owners_pixel_stays_chosen(client: TestClient, db: Session) -> None:
    launch = _launch(client, db)
    _pixel(db, launch, "1", events=[{"event": "Lead", "count": 3}])
    _pixel(db, launch, "2", events=[{"event": "PageView", "count": 900}])
    launch.answers = {**launch.answers, "pixel_id": "1"}
    db.commit()

    found = chosen_pixel(db, launch=launch)

    assert found is not None and found.external_id == "1"


def test_each_event_has_its_seven_day_count_and_warning(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db)
    _pixel(
        db,
        launch,
        "1",
        events=[
            {"event": "Lead", "count": 312},
            {"event": "CompleteRegistration", "count": 4},
        ],
    )

    choices = conversion_event_choices(db, launch=launch)

    assert choices is not None
    by_key = {
        row.key: row for row in (*choices.arriving_options, *choices.other_options)
    }
    assert (by_key["LEAD"].count, by_key["LEAD"].warning) == (312, "")
    assert (
        by_key["COMPLETE_REGISTRATION"].count,
        by_key["COMPLETE_REGISTRATION"].warning,
    ) == (4, EVENT_FEW)
    assert (by_key["CONTACT"].count, by_key["CONTACT"].warning) == (
        0,
        EVENT_NOT_ARRIVING,
    )
    # Every event is offered, shopping ones too: the objective follows the pick.
    assert "PURCHASE" in by_key


def test_lead_is_the_usual_pick_when_the_site_sends_it(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db)
    _pixel(
        db,
        launch,
        "1",
        events=[
            {"event": "CompleteRegistration", "count": 900},
            {"event": "Lead", "count": 2},
        ],
    )

    apply_conversion_event(db, launch=launch)

    assert effective_conversion_event(db, launch=launch) == "LEAD"


def test_a_pick_with_no_events_is_warned_about_not_refused(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db)
    _pixel(db, launch, "1", events=[{"event": "Lead", "count": 5}])

    choose_conversion_event(db, launch=launch, key="SCHEDULE")

    assert launch.answers[CONVERSION_EVENT] == "SCHEDULE"


def test_a_custom_conversion_is_offered_and_sent_with_its_type(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db)
    _pixel(
        db,
        launch,
        "1",
        events=[{"event": "Lead", "count": 5}],
        conversions=[
            {"id": "55", "name": "Rahmat sahifasi", "event": "LEAD", "count": 7},
            # A type this product cannot buy on is not offered at all.
            {"id": "56", "name": "Mahsulot", "event": "CUSTOMIZE_PRODUCT"},
        ],
    )

    choices = conversion_event_choices(db, launch=launch)
    assert choices is not None
    custom = [
        row
        for row in (*choices.arriving_options, *choices.other_options)
        if row.group == "custom"
    ]
    assert [(row.key, row.label, row.count) for row in custom] == [
        ("cc:55", "Rahmat sahifasi", 7)
    ]

    choose_conversion_event(db, launch=launch, key="cc:55")
    answers = launch_answers(
        db, launch=launch, business=launch_business(db, launch=launch)
    )

    assert (answers.conversion_event, answers.custom_conversion_id) == ("LEAD", "55")


def test_the_sweep_keeps_each_pixels_custom_conversions(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    launch = _launch(client, db)
    pixel = _pixel(db, launch, "1", events=[])
    account = launch.ad_account
    assert account is not None
    monkeypatch.setattr(sync, "_usable_token", lambda connection: "t")
    monkeypatch.setattr(
        sync,
        "pixel_events",
        lambda **_: [PixelEventRow(event="Lead", count=9)],
    )
    monkeypatch.setattr(
        sync,
        "custom_conversions",
        lambda **_: [
            CustomConversionRow(
                id="55",
                name="Rahmat",
                custom_event_type="LEAD",
                pixel_id="1",
                last_fired_time=datetime(2026, 11, 6, tzinfo=UTC),
            ),
            CustomConversionRow(id="56", name="Eski", pixel_id="1", is_archived=True),
            CustomConversionRow(id="57", name="Boshqa", pixel_id="other"),
        ],
    )
    monkeypatch.setattr(sync, "custom_conversion_count", lambda **_: 7)

    sync.sync_pixel_events(db, ad_account_id=account.id)
    db.refresh(pixel)

    assert pixel.recent_events == [{"event": "Lead", "count": 9}]
    assert [(row["id"], row["event"], row["count"]) for row in pixel.conversions] == [
        ("55", "LEAD", 7)
    ]
