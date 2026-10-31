"""The editor's places: the search, a pick from it, and a radius on the map."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from adskit import ExternalRef
from adskit.dto import LocationDTO
from adskit.errors import TemporaryFailure
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import DraftSection
from app.modules.ads.models import CampaignLaunch, GoogleLaunch
from app.modules.ads.routers import drafts
from app.modules.ads.services import locations
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount
from tests.pg.test_launch_drafts import _opened


def _place(key: str, name: str, *, kind: str = "city", country: str = "UZ") -> Any:
    return LocationDTO(
        ref=ExternalRef(provider="meta", id=key, level="location"),
        name=name,
        kind=kind,
        country_code=country,
        context=f"{name}, {country}",
        parent_id="77" if kind == "city" and country == "UZ" else "",
    )


TASHKENT = _place("2420901", "Tashkent")
TASHKENT_KZ = _place("2510990", "Tashkent", country="KZ")


class Audiences:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self.failing = False

    def find_locations(
        self, *, query: str, country_code: str, token: str, language: str = ""
    ) -> list[LocationDTO]:
        self.asked.append(query)
        if self.failing:
            raise TemporaryFailure("meta is down")
        return [TASHKENT, TASHKENT_KZ, _place("9", "Tash Bay", kind="other")]


@pytest.fixture
def meta(monkeypatch: pytest.MonkeyPatch) -> Audiences:
    fake = Audiences()
    monkeypatch.setitem(drafts.READING, "poll_seconds", 0)
    monkeypatch.setattr(
        locations,
        "registry",
        SimpleNamespace(get=lambda _provider: SimpleNamespace(audiences=fake)),
    )
    monkeypatch.setattr(
        locations, "launch_account_and_token", lambda *_a, **_k: (None, "t")
    )
    monkeypatch.setattr(locations, "SEARCH_CACHE_PREFIX", f"{uuid.uuid4()}:")
    return fake


def _proposal(
    client: TestClient, db: Session, *, geo: dict[str, Any] | None = None
) -> tuple[dict[str, str], str, CampaignLaunch]:
    auth, draft_id = _opened(client, db)
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    proposal = draft_field.empty_draft()
    draft_field.choose(
        proposal,
        DraftSection.AUDIENCE,
        {"age_min": 25, "age_max": 45, "genders": [], "geo": geo or {}},
    )
    launch.draft = proposal
    launch.answers = {**launch.answers, "goal": "traffic"}
    launch.status = "ready"
    launch.targeting = {"geo_locations": {"countries": ["UZ"]}}
    db.commit()
    return auth, f"/api/v1/launch/drafts/{draft_id}", launch


def _stored(db: Session, launch: CampaignLaunch) -> dict[str, Any]:
    db.refresh(launch)
    chosen = draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    return geo_field.stored(chosen)


def test_the_search_answers_the_world_the_chosen_country_first(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, _launch = _proposal(client, db)

    home = client.get(f"{path}/locations?q=Tashkent", headers=auth)
    assert home.status_code == 200, home.text
    rows = home.json()
    assert [row["countryCode"] for row in rows] == ["UZ", "KZ"]
    assert rows[0] == {
        "id": "2420901",
        "name": "Tashkent",
        "type": "city",
        "context": "Tashkent, UZ",
        "countryCode": "UZ",
    }

    abroad = client.get(f"{path}/locations?q=tashkent&country=kz", headers=auth).json()
    assert [row["countryCode"] for row in abroad] == ["KZ", "UZ"]
    assert meta.asked == ["Tashkent"], "the second spelling came from the cache"


def test_too_little_typed_asks_nobody(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, _launch = _proposal(client, db)
    assert client.get(f"{path}/locations?q=T", headers=auth).json() == []
    assert client.get(f"{path}/locations", headers=auth).json() == []
    assert meta.asked == []


def test_a_bad_country_is_refused_by_the_request(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, _launch = _proposal(client, db)
    bad = client.get(f"{path}/locations?q=Tashkent&country=UZB", headers=auth)
    assert bad.status_code == 422


def test_a_search_meta_cannot_answer_says_so(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, _launch = _proposal(client, db)
    meta.failing = True
    down = client.get(f"{path}/locations?q=Tashkent", headers=auth)
    assert down.status_code == 503
    assert down.json()["code"] == "place_search_failed"


def test_the_search_has_a_limit(
    client: TestClient,
    db: Session,
    queued: list,
    meta: Audiences,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth, path, _launch = _proposal(client, db)
    monkeypatch.setattr(
        "app.modules.ads.routers.drafts_review.GEO_SEARCHES_PER_MINUTE", 1
    )
    assert client.get(f"{path}/locations?q=Tashkent", headers=auth).status_code == 200
    assert client.get(f"{path}/locations?q=Tashkent", headers=auth).status_code == 429


def test_a_draft_that_is_not_the_users_finds_nothing(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, _path, _launch = _proposal(client, db)
    other = client.get(
        f"/api/v1/launch/drafts/{uuid.uuid4()}/locations?q=Tashkent", headers=auth
    )
    assert other.status_code == 404


def test_a_google_draft_has_no_meta_search(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, _path, _launch = _proposal(client, db)
    user = db.scalar(select(User))
    account = db.scalar(select(AdAccount))
    assert user is not None and account is not None
    google = GoogleLaunch(
        owner_id=user.id,
        ad_account_id=account.id,
        currency="USD",
        final_url="https://bahor.example",
        phone="",
        places=[],
        keywords=[],
        negative_keywords=[],
        headlines=[],
        descriptions=[],
        volumes={},
        created_refs={},
    )
    db.add(google)
    db.commit()
    answer = client.get(
        f"/api/v1/launch/drafts/{google.id}/locations?q=Tashkent", headers=auth
    )
    assert answer.status_code == 404
    assert meta.asked == []


def test_a_row_of_the_search_is_saved_with_its_key(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, launch = _proposal(client, db)
    tabs = client.get(f"{path}/edit", headers=auth).json()
    row = client.get(f"{path}/locations?q=Tashkent", headers=auth).json()[0]

    tabs["geo"]["places"] = [row]
    saved = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert saved.status_code == 200, saved.text

    geo = _stored(db, launch)
    assert geo["mode"] == "places" and geo["queries"] == []
    assert geo["places"] == [
        {"key": "2420901", "name": "Tashkent", "kind": "city", "parent": "77"}
    ]
    db.refresh(launch)
    assert launch.targeting["geo_locations"]["cities"] == [{"key": "2420901"}]
    shown = client.get(f"{path}/edit", headers=auth).json()["geo"]["places"]
    assert [place["id"] for place in shown] == ["2420901"]


def test_a_key_the_search_never_offered_is_refused(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, launch = _proposal(client, db)
    tabs = client.get(f"{path}/edit", headers=auth).json()
    tabs["geo"]["places"] = [{"id": "666", "name": "Tashkent", "type": "city"}]
    refused = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert refused.status_code == 422
    assert "audience.places" in refused.json()["problems"]
    assert _stored(db, launch)["places"] == []


def test_a_place_only_offered_is_not_shown_as_chosen(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    row = {"key": "1", "name": "Tashkent", "kind": "city", "parent": ""}
    auth, path, _launch = _proposal(
        client,
        db,
        geo={
            "mode": "places",
            "places": [],
            "candidates": [{"query": "Tashkent", "places": [row]}],
        },
    )
    assert client.get(f"{path}/edit", headers=auth).json()["geo"]["places"] == []


def test_a_radius_on_the_map_is_saved_with_its_pin_and_address(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, launch = _proposal(client, db)
    tabs = client.get(f"{path}/edit", headers=auth).json()
    assert (tabs["geo"]["minKm"], tabs["geo"]["maxKm"]) == (1, 80)
    assert tabs["geo"]["placeLimit"] == 10

    tabs["geo"] |= {
        "mode": "map",
        "km": 12,
        "lat": 52.520008,
        "lng": 13.404954,
        "address": "Alexanderplatz, Berlin",
    }
    saved = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert saved.status_code == 200, saved.text

    db.refresh(launch)
    pin = launch.targeting["geo_locations"]["custom_locations"][0]
    assert pin["radius"] == 12 and pin["distance_unit"] == "kilometer"
    assert (float(pin["latitude"]), float(pin["longitude"])) == (52.520008, 13.404954)
    shown = client.get(f"{path}/edit", headers=auth).json()["geo"]
    assert shown["mode"] == "map" and shown["km"] == 12
    assert shown["address"] == "Alexanderplatz, Berlin"
    assert (shown["lat"], shown["lng"]) == (52.520008, 13.404954)


def test_a_radius_outside_the_band_is_refused(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, _launch = _proposal(client, db)
    tabs = client.get(f"{path}/edit", headers=auth).json()
    tabs["geo"] |= {"mode": "map", "km": 200, "lat": 41.3, "lng": 69.2}
    refused = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert refused.status_code == 422
    assert "geo.km" in refused.json()["problems"]


def test_a_special_category_raises_the_floor(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, _launch = _proposal(client, db)
    business = db.scalar(select(Business))
    assert business is not None
    business.special_ad_category = "HOUSING"
    db.commit()
    tabs = client.get(f"{path}/edit", headers=auth).json()
    assert tabs["geo"]["minKm"] == 24
    tabs["geo"] |= {"mode": "map", "km": 10, "lat": 41.3, "lng": 69.2}
    assert client.put(f"{path}/edit", json=tabs, headers=auth).status_code == 422


def test_a_map_without_a_pin_is_refused(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, path, _launch = _proposal(client, db)
    tabs = client.get(f"{path}/edit", headers=auth).json()
    tabs["geo"] |= {"mode": "map", "km": 5, "lat": 0.0, "lng": 0.0}
    refused = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert refused.status_code == 422
    assert "audience.geo_mode" in refused.json()["problems"]


def test_an_unchanged_save_leaves_a_derived_place_derived(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    row = {"key": "1", "name": "Tashkent", "kind": "city", "parent": ""}
    auth, path, launch = _proposal(
        client, db, geo={"mode": "places", "places": [row], "origin": "derived"}
    )
    tabs = client.get(f"{path}/edit", headers=auth).json()
    for place in tabs["geo"]["places"]:
        place |= {"context": "ignored by the save"}
    saved = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert saved.status_code == 200, saved.text
    assert _stored(db, launch)["origin"] == "derived"
