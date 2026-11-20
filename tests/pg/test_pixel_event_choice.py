"""TZ 3: the pixel, its events with seven-day counts, custom conversions."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from metaads.dto import CustomConversionRow, PixelDTO, PixelEventRow
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.constants import CONVERSION_EVENT, EVENT_FEW, EVENT_NOT_ARRIVING
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.routers.launch_common import launch_business
from app.modules.ads.selectors.advice import conversion_event_recommendation
from app.modules.ads.selectors.conversion_event import (
    conversion_event_choices,
    effective_conversion_event,
    offered_keys,
)
from app.modules.ads.selectors.pixel import chosen_pixel, pixel_choices, usable_pixels
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
    _pixel(db, launch, "1", events=[{"event": "Lead", "count": 3}])
    _pixel(db, launch, "2", events=[{"event": "PageView", "count": 900}])

    found = chosen_pixel(db, launch=launch)

    # Visits are not leads: the pixel the site sends its leads through wins.
    assert found is not None and found.external_id == "1"


def test_a_pixel_with_no_site_results_falls_back_to_the_busiest(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db)
    _pixel(db, launch, "1", events=[{"event": "ViewContent", "count": 30}])
    _pixel(db, launch, "2", events=[{"event": "PageView", "count": 900}])

    found = chosen_pixel(db, launch=launch)

    assert found is not None and found.external_id == "2"


def test_the_crm_pixel_does_not_win_over_the_sites_lead_pixel(
    client: TestClient, db: Session
) -> None:
    """Production, 2026-11-20: the cabinet's pixel got only CRM verdicts."""
    launch = _launch(client, db)
    _pixel(
        db,
        launch,
        "1",
        active=True,
        events=[{"event": "TargetologAIDisqualifiedLead", "count": 1}],
    )
    _pixel(
        db,
        launch,
        "2",
        events=[
            {"event": "PageView", "count": 11337},
            {"event": "Lead", "count": 540, "web": 532, "server": 540},
        ],
    )

    found = chosen_pixel(db, launch=launch)
    options = {row.external_id: row for row in pixel_choices(db, launch=launch)}

    assert found is not None and found.external_id == "2"
    assert (options["1"].site_results, options["2"].site_results) == (0, 532)
    assert options["2"].is_chosen


def test_the_pixel_chosen_in_the_cabinet_beats_a_busier_one(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db)
    _pixel(db, launch, "1", events=[{"event": "Lead", "count": 3}], active=True)
    _pixel(db, launch, "2", events=[{"event": "PageView", "count": 900}])

    found = chosen_pixel(db, launch=launch)

    assert found is not None and found.external_id == "1"


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
            # A type Meta added after our list is offered as well (TZ 3).
            {"id": "56", "name": "Bron", "event": "SERVICE_BOOKING_REQUEST"},
        ],
    )

    choices = conversion_event_choices(db, launch=launch)
    assert choices is not None
    custom = [
        row
        for row in (*choices.arriving_options, *choices.other_options)
        if row.group == "custom"
    ]
    assert sorted((row.key, row.label, row.count) for row in custom) == [
        ("cc:55", "Rahmat sahifasi", 7),
        ("cc:56", "Bron", None),
    ]

    choose_conversion_event(db, launch=launch, key="cc:55")
    answers = launch_answers(
        db, launch=launch, business=launch_business(db, launch=launch)
    )

    assert (answers.conversion_event, answers.custom_conversion_id) == ("LEAD", "55")

    choose_conversion_event(db, launch=launch, key="cc:56")
    answers = launch_answers(
        db, launch=launch, business=launch_business(db, launch=launch)
    )

    assert (answers.conversion_event, answers.custom_conversion_id) == (
        "SERVICE_BOOKING_REQUEST",
        "56",
    )


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
        "pixel_events_by_source",
        lambda **_: [PixelEventRow(event="Lead", count=9, web=9, server=4)],
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

    assert pixel.recent_events == [{"event": "Lead", "count": 9, "web": 9, "server": 4}]
    assert [(row["id"], row["event"], row["count"]) for row in pixel.conversions] == [
        ("55", "LEAD", 7)
    ]


def test_an_empty_answer_about_a_pixel_that_fired_keeps_the_last_figures(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    launch = _launch(client, db)
    kept = [{"event": "Lead", "count": 40, "web": 40, "server": 0}]
    pixel = _pixel(db, launch, "1", events=kept)
    pixel.last_fired_at = utcnow()
    synced = pixel.events_synced_at
    db.commit()
    account = launch.ad_account
    assert account is not None
    asked: list[str] = []
    monkeypatch.setattr(sync, "_usable_token", lambda connection: "t")
    monkeypatch.setattr(sync, "pixel_events_by_source", lambda **_: [])
    monkeypatch.setattr(
        sync, "pixel_events", lambda **kw: asked.append(kw["pixel_id"]) or []
    )
    monkeypatch.setattr(sync, "custom_conversions", lambda **_: [])

    sync.sync_pixel_events(db, ad_account_id=account.id)
    db.refresh(pixel)

    assert asked == ["1"]
    assert pixel.recent_events == kept
    assert pixel.events_synced_at == synced


def test_an_empty_answer_about_a_quiet_pixel_is_believed(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    launch = _launch(client, db)
    pixel = _pixel(db, launch, "1", events=[{"event": "Lead", "count": 3}])
    pixel.last_fired_at = None
    db.commit()
    account = launch.ad_account
    assert account is not None
    monkeypatch.setattr(sync, "_usable_token", lambda connection: "t")
    monkeypatch.setattr(sync, "pixel_events_by_source", lambda **_: [])
    monkeypatch.setattr(sync, "custom_conversions", lambda **_: [])

    sync.sync_pixel_events(db, ad_account_id=account.id)
    db.refresh(pixel)

    assert pixel.recent_events == []


def test_a_pixel_meta_stopped_listing_is_kept_unusable(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    launch = _launch(client, db)
    gone = _pixel(db, launch, "1", events=[], active=True)
    _pixel(db, launch, "2", events=[])
    account = launch.ad_account
    assert account is not None

    sync._store_pixels(db, account=account, pixels=[PixelDTO(id="2", name="Pixel 2")])
    db.commit()
    db.refresh(gone)

    assert gone.is_unavailable is True and gone.is_active is False
    assert [row.external_id for row in usable_pixels(db, launch=launch)] == ["2"]


def _site_pixel(client: TestClient, db: Session) -> tuple[CampaignLaunch, PixelAccount]:
    launch = _launch(client, db)
    pixel = _pixel(
        db,
        launch,
        "1",
        active=True,
        events=[
            {"event": "PageView", "count": 900},
            {"event": "Lead", "count": 40},
            {"event": "new_lead", "count": 37, "web": 37, "server": 0},
            {"event": "purchase", "count": 3},
            {"event": "TargetologAIQualifiedLead", "count": 9},
            {"event": "good_lead", "count": 12},
        ],
        conversions=[
            {"id": "77", "name": "Yaxshi", "event": "LEAD", "rule_event": "good_lead"}
        ],
    )
    return launch, pixel


def test_the_sites_own_events_are_offered_beside_the_standard_ones(
    client: TestClient, db: Session
) -> None:
    launch, _pixel_row = _site_pixel(client, db)

    choices = conversion_event_choices(db, launch=launch)
    assert choices is not None
    own = [
        (row.key, row.label, row.count)
        for row in (*choices.arriving_options, *choices.other_options)
        if row.group == "site_event"
    ]

    # Standard names, our own CRM verdicts and an event a conversion already
    # counts are not offered again; a lower-case «purchase» is the site's own.
    assert own == [("ev:new_lead", "new_lead", 37), ("ev:purchase", "purchase", 3)]


def test_picking_a_site_event_makes_its_custom_conversion(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    from app.modules.ads.services import advanced

    launch, pixel = _site_pixel(client, db)
    made: list[dict[str, Any]] = []
    monkeypatch.setattr(
        advanced, "create_custom_conversion", lambda **kw: made.append(kw) or "901"
    )
    monkeypatch.setattr("app.modules.ads.services.access.token_for", lambda **_: "t")

    choose_conversion_event(db, launch=launch, key="ev:new_lead")
    db.refresh(pixel)
    answers = launch_answers(
        db, launch=launch, business=launch_business(db, launch=launch)
    )

    assert [(kw["pixel_id"], kw["event"], kw["custom_event_type"]) for kw in made] == [
        ("1", "new_lead", "LEAD")
    ]
    assert launch.answers[CONVERSION_EVENT] == "cc:901"
    assert (answers.conversion_event, answers.custom_conversion_id) == ("LEAD", "901")
    assert pixel.conversions[-1]["rule_event"] == "new_lead"


def test_a_refused_conversion_says_so_and_keeps_the_event(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    from metaads.errors import MetaError

    from app.modules.ads.exceptions import SiteEventRefused
    from app.modules.ads.services import advanced

    launch, _pixel_row = _site_pixel(client, db)

    def refuse(**_: Any) -> str:
        raise MetaError("limit reached")

    monkeypatch.setattr(advanced, "create_custom_conversion", refuse)
    monkeypatch.setattr("app.modules.ads.services.access.token_for", lambda **_: "t")

    with pytest.raises(SiteEventRefused):
        choose_conversion_event(db, launch=launch, key="ev:new_lead")
    assert CONVERSION_EVENT not in launch.answers


def test_a_lead_goal_is_not_moved_to_what_the_site_happens_to_send(
    client: TestClient, db: Session
) -> None:
    launch = _launch(client, db)
    _pixel(db, launch, "1", events=[{"event": "ViewContent", "count": 900}])

    advice = conversion_event_recommendation(
        db, launch=launch, offered=offered_keys(db, launch=launch)
    )

    # ViewContent would make the builder buy it as sales.
    assert advice is not None and advice.value == "LEAD"


def test_other_alone_is_not_offered(client: TestClient, db: Session) -> None:
    launch = _launch(client, db)
    _pixel(db, launch, "1", events=[{"event": "Lead", "count": 9}])

    assert "OTHER" not in offered_keys(db, launch=launch)


def test_the_ais_event_follows_a_new_pixel_and_the_owners_stays(
    client: TestClient, db: Session
) -> None:
    from app.modules.ads import draft as draft_field
    from app.modules.ads.services.advanced import choose_pixel

    launch = _launch(client, db)
    _pixel(db, launch, "1", events=[{"event": "Lead", "count": 30}])
    _pixel(db, launch, "2", events=[{"event": "Contact", "count": 12}])
    apply_conversion_event(db, launch=launch)
    assert draft_field.conversion_event(launch.draft) == "LEAD"

    choose_pixel(db, launch=launch, external_id="2")

    assert draft_field.conversion_event(launch.draft) == "CONTACT"

    choose_conversion_event(db, launch=launch, key="SCHEDULE")
    choose_pixel(db, launch=launch, external_id="1")

    assert launch.answers[CONVERSION_EVENT] == "SCHEDULE"
