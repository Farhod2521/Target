"""«Kim tanlaydi?»: the editor is told what each mode sends, and the card shows it.

The screen keeps no default, badge or age limit of its own: it draws from
``rules``. What a mode never sends is not shown on the card either.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.models import CampaignLaunch
from app.modules.businesses.models import Business
from tests.pg.test_launch_editor_save import _launch


def _edit_url(launch: CampaignLaunch) -> str:
    return f"/api/v1/launch/drafts/{launch.id}/edit"


def _save(client: TestClient, launch: CampaignLaunch, auth: dict, change) -> None:
    """Through the editor, as the owner would: read, change, save."""
    edit = client.get(_edit_url(launch), headers=auth).json()
    change(edit)
    saved = client.put(_edit_url(launch), json=edit, headers=auth)
    assert saved.status_code == 200, saved.text


def _card(client: TestClient, launch: CampaignLaunch, auth: dict) -> dict:
    read = client.get(f"/api/v1/launch/drafts/{launch.id}", headers=auth)
    assert read.status_code == 200, read.text
    return read.json()["proposal"]


def test_the_editor_is_told_what_each_mode_sends(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)

    rules = client.get(_edit_url(launch), headers=auth).json()["rules"]

    assert rules["default"] == "auto"
    assert rules["recommended"] == "auto"
    assert rules["recommendedNote"]
    assert rules["locked"] is False
    modes = {row["value"]: row for row in rules["modes"]}
    assert list(modes) == ["auto", "interests", "broad"]
    auto = modes["auto"]
    assert auto["fields"] == {
        "interests": "unused",
        "habits": "unused",
        "genders": "hint",
        "includeLists": "hint",
    }
    assert auto["age"] == {
        "min": 18,
        "max": 65,
        "lowestMax": 25,
        "upperSent": False,
        "fixed": False,
    }
    assert "yuborilmaydi" in auto["note"]
    assert modes["interests"]["fields"]["interests"] == "required"
    assert modes["interests"]["fields"]["habits"] == "exact"
    assert modes["interests"]["age"]["upperSent"] is True
    assert modes["broad"]["fields"]["interests"] == "unused"
    assert modes["broad"]["fields"]["genders"] == "exact"


def test_a_special_category_is_one_mode_with_nothing_to_choose(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)
    business = db.scalar(select(Business).where(Business.user_id == launch.owner_id))
    assert business is not None
    business.special_ad_category = "housing"
    db.commit()

    rules = client.get(_edit_url(launch), headers=auth).json()["rules"]

    assert rules["locked"] is True
    assert rules["recommended"] is None
    assert len(rules["modes"]) == 1
    only = rules["modes"][0]
    assert only["fields"]["genders"] == "unused"
    assert only["fields"]["interests"] == "unused"
    assert only["age"]["fixed"] is True


def test_the_rules_sent_back_on_save_are_ignored(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)
    edit = client.get(_edit_url(launch), headers=auth).json()
    edit["rules"]["default"] = "broad"
    edit["rules"]["modes"] = []

    saved = client.put(_edit_url(launch), json=edit, headers=auth)

    assert saved.status_code == 200, saved.text
    assert client.get(_edit_url(launch), headers=auth).json()["rules"]["default"] == (
        "auto"
    )


def test_the_card_shows_what_the_automatic_mode_sends(
    client: TestClient, db: Session, queued: list
) -> None:
    """Interests reach nobody here, and Meta keeps no age above 25 at the low end
    and no upper one: 30-50 typed goes out as 25-65+."""
    launch, auth = _launch(client, db)

    def change(edit: dict) -> None:
        edit["aud"]["who"] = "auto"
        edit["aud"]["age"] = [30, 50]
        edit["interests"] = ["Restaurants"]

    _save(client, launch, auth, change)

    audience = _card(client, launch, auth)["audience"]

    assert audience["age"] == [25, 65]
    assert audience["interests"] == []


def test_the_card_shows_the_interests_and_ages_of_the_interests_mode(
    client: TestClient, db: Session, queued: list
) -> None:
    launch, auth = _launch(client, db)

    def change(edit: dict) -> None:
        edit["aud"]["who"] = "interests"
        edit["aud"]["age"] = [30, 50]
        edit["interests"] = ["Restaurants"]

    _save(client, launch, auth, change)

    audience = _card(client, launch, auth)["audience"]

    assert audience["age"] == [30, 50]
    assert audience["interests"] == ["Restaurants"]


def test_the_interests_mode_with_none_found_is_said_before_the_press(
    client: TestClient, db: Session, queued: list
) -> None:
    """The gate refuses it at the press; the card says it first, and why."""
    launch, auth = _launch(client, db)

    def change(edit: dict) -> None:
        edit["aud"]["who"] = "interests"
        edit["interests"] = []
        edit["habits"] = []

    _save(client, launch, auth, change)
    db.refresh(launch)
    assert not (launch.targeting or {}).get("flexible_spec")

    blockers = _card(client, launch, auth)["blockers"]

    assert [row["id"] for row in blockers] == ["interests_missing"]
    assert blockers[0]["action"]["to"] == "int"


def test_an_unfound_interest_is_named_only_where_the_mode_sends_interests(
    client: TestClient, db: Session, queued: list
) -> None:
    """Nothing answers the search here, so the name stays unconfirmed."""
    launch, auth = _launch(client, db)
    for who, shown in (("interests", True), ("auto", False)):

        def change(edit: dict, who: str = who) -> None:
            edit["aud"]["who"] = who
            edit["interests"] = ["Nimadir topilmas"]

        _save(client, launch, auth, change)

        notes = {row["id"]: row for row in _card(client, launch, auth)["attention"]}

        assert ("interests_unconfirmed" in notes) is shown, who
        if shown:
            assert "Nimadir topilmas" in notes["interests_unconfirmed"]["text"]


def test_a_geography_nobody_chose_is_said_and_a_pin_settles_it(
    client: TestClient, db: Session, queued: list
) -> None:
    """The fixture's business has no pin and no regions: the whole country,
    which nobody asked for. A pin with a distance is named on the card."""
    launch, auth = _launch(client, db)

    def rebuild(edit: dict) -> None:
        edit["aud"]["age"] = [20, 40]

    _save(client, launch, auth, rebuild)
    before = _card(client, launch, auth)
    notes = {row["id"]: row for row in before["attention"]}
    assert notes["geo_widened"]["action"]["to"] == "geo"

    def change(edit: dict) -> None:
        edit["geo"] |= {
            "mode": "map",
            "lat": 41.3111,
            "lng": 69.2406,
            "km": 7,
            "address": "Chilonzor",
        }

    _save(client, launch, auth, change)
    after = _card(client, launch, auth)

    assert after["audience"]["places"] == ["Chilonzor · 7 km atrofida"]
    assert "geo_widened" not in {row["id"] for row in after["attention"]}


def test_the_interest_search_offers_metas_interests_only(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A behaviour found under the word is not offered: the tab's names are
    confirmed against the interest catalogue, and it would never be found."""
    coffee = {"id": "11", "name": "Coffee", "kind": "interests"}
    monkeypatch.setattr(
        "app.modules.ads.services.audience_search._kept",
        lambda _key, _ask: [
            {**coffee, "path": "Interests · Food", "lower": 10, "upper": 20},
            {
                "id": "12",
                "name": "Coffee lovers",
                "kind": "behaviors",
                "path": "",
                "lower": 1,
                "upper": 2,
            },
        ],
    )
    launch, auth = _launch(client, db)
    url = f"/api/v1/launch/drafts/{launch.id}/interests"

    found = client.get(f"{url}?q=coffee", headers=auth)
    empty = client.get(f"{url}?q=", headers=auth)

    assert found.status_code == 200, found.text
    assert found.json() == [
        {**coffee, "path": "Interests · Food", "lower": 10, "upper": 20}
    ]
    assert empty.json() == []


def test_the_interest_search_is_throttled_like_the_place_search(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch, auth = _launch(client, db)
    monkeypatch.setattr(
        "app.modules.ads.routers.drafts_review.throttle.hit", lambda **_k: False
    )

    answer = client.get(
        f"/api/v1/launch/drafts/{launch.id}/interests?q=coffee", headers=auth
    )

    assert answer.status_code == 429


def test_a_special_category_card_names_no_gender_it_never_sends(
    client: TestClient, db: Session, queued: list
) -> None:
    """The law strips genders from the spec; a gender saved earlier is not shown."""
    launch, auth = _launch(client, db)

    def women(edit: dict) -> None:
        edit["aud"]["genders"] = ["f"]

    _save(client, launch, auth, women)
    assert _card(client, launch, auth)["audience"]["genders"] == "f"
    business = db.scalar(select(Business).where(Business.user_id == launch.owner_id))
    assert business is not None
    business.special_ad_category = "housing"
    db.commit()

    assert _card(client, launch, auth)["audience"]["genders"] == "all"
