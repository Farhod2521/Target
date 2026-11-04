"""Who the business sells to and where it works: kept on the profile, and a new
advert's audience starts from them."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from adskit import ExternalRef
from adskit.dto import LocationDTO
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import draft as draft_field
from app.modules.ads.constants import DraftSection
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.services import locations, proposal
from app.modules.ads.services.targeting import business_genders, suggested_geo
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import business_for
from core.agent.schemas import AudienceProposal, LaunchDraft
from tests.pg.test_launch_api import _ready
from tests.pg.test_launch_proposal_patch import _reviewed

PROFILE = {
    "name": "Bahor",
    "category": "restaurant",
    "country_code": "UZ",
    "timezone": "Asia/Tashkent",
}


def _place(key: str, name: str, *, kind: str = "city", country: str = "UZ") -> Any:
    return LocationDTO(
        ref=ExternalRef(provider="meta", id=key, level="location"),
        name=name,
        kind=kind,
        country_code=country,
        context=f"{name}, {country}",
        parent_id="",
    )


class Audiences:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def find_locations(
        self, *, query: str, country_code: str, token: str, language: str = ""
    ) -> list[LocationDTO]:
        self.asked.append(query)
        return [
            _place("2510990", "Tashkent", country="KZ"),
            _place("2420901", "Tashkent"),
            _place("2420877", "Samarqand"),
        ]


@pytest.fixture
def meta(monkeypatch: pytest.MonkeyPatch) -> Audiences:
    fake = Audiences()
    monkeypatch.setattr(
        locations,
        "registry",
        SimpleNamespace(get=lambda _provider: SimpleNamespace(audiences=fake)),
    )
    monkeypatch.setattr(locations, "account_and_token", lambda *_a, **_k: (None, "t"))
    monkeypatch.setattr(locations, "SEARCH_CACHE_PREFIX", f"{uuid.uuid4()}:")
    return fake


def _save(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    return client.put("/api/v1/business", json=PROFILE | fields, headers=auth)


def test_the_search_finds_places_with_the_business_country_first(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, _user = _ready(client, db)

    found = client.get("/api/v1/business/locations?q=Tash", headers=auth)

    assert found.status_code == 200, found.text
    assert [row["country_code"] for row in found.json()] == ["UZ", "UZ", "KZ"]
    assert found.json()[0] == {
        "id": "2420901",
        "name": "Tashkent",
        "type": "city",
        "context": "Tashkent, UZ",
        "country_code": "UZ",
    }
    assert client.get("/api/v1/business/locations?q=T", headers=auth).json() == []


def test_the_profile_keeps_whom_it_sells_to_and_where(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, _user = _ready(client, db)
    picked = {"key": "2420901", "name": "Tashkent", "kind": "city", "country_code": ""}

    saved = _save(client, auth, audience_gender="female", regions=[picked, picked])

    assert saved.status_code == 200, saved.text
    assert saved.json()["audience_gender"] == "female"
    assert saved.json()["regions"] == [
        {"key": "2420901", "name": "Tashkent", "kind": "city", "country_code": "UZ"}
    ]
    shown = client.get("/api/v1/business", headers=auth).json()["business"]
    assert (shown["audience_gender"], len(shown["regions"])) == ("female", 1)

    asked = len(meta.asked)
    kept = _save(client, auth, name="Bahor 2")
    assert kept.status_code == 200, kept.text
    assert kept.json()["regions"][0]["key"] == "2420901"
    assert kept.json()["audience_gender"] == "female"
    again = _save(client, auth, regions=kept.json()["regions"])
    assert again.status_code == 200, again.text
    assert len(meta.asked) == asked


def test_a_place_the_search_did_not_offer_is_refused(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, _user = _ready(client, db)

    refused = _save(
        client,
        auth,
        regions=[{"key": "666", "name": "Tashkent", "kind": "city"}],
    )

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == "Joylardan birini qidiruvdan qayta tanlang."


def test_a_new_advert_starts_from_the_profile(
    client: TestClient, db: Session, queued: list, meta: Audiences
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)
    picked = {"key": "2420877", "name": "Samarqand", "kind": "city"}
    assert (
        _save(client, auth, audience_gender="male", regions=[picked]).status_code == 200
    )
    business = business_for(db, user)
    assert business is not None
    db.refresh(business)
    answer: Any = LaunchDraft.model_construct(
        audience=AudienceProposal.model_construct(
            age_min=20, age_max=45, genders=[2], radius_km=5, reason=""
        ),
        interests=[],
        creatives=[],
        form_questions=[],
        traits=[],
    )

    assert proposal._store(
        db, launch=launch, business=business, proposal=answer, problems=[], run=""
    )

    db.refresh(launch)
    audience = draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    assert audience["genders"] == [1]
    assert audience["geo"]["mode"] == "places"
    assert [row["key"] for row in audience["geo"]["places"]] == ["2420877"]
    assert launch.targeting["genders"] == [1]
    assert launch.targeting["geo_locations"] == {"cities": [{"key": "2420877"}]}


def test_the_account_profile_speaks_where_the_page_profile_is_silent(
    client: TestClient, db: Session, queued: list
) -> None:
    _auth, user = _ready(client, db)
    page_profile = business_for(db, user)
    assert page_profile is not None and page_profile.page_id is not None
    db.add(
        Business(
            user_id=user.id,
            name="Bahor",
            timezone="Asia/Tashkent",
            country_code="UZ",
            audience_gender="female",
            regions=[{"key": "2420877", "name": "Samarqand", "kind": "city"}],
        )
    )
    db.commit()

    assert business_genders(db, owner=user, business=page_profile) == [2]
    geo = suggested_geo(db, owner=user, business=page_profile)
    assert (geo.mode, [place.key for place in geo.places]) == ("places", ["2420877"])

    page_profile.special_ad_category = "HOUSING"
    db.commit()
    assert business_genders(db, owner=user, business=page_profile) is None


def test_with_nothing_on_the_profile_the_advert_starts_as_before(
    client: TestClient, db: Session, queued: list
) -> None:
    _auth, user = _ready(client, db)
    business = db.scalar(select(Business).where(Business.user_id == user.id))
    assert business is not None

    assert business_genders(db, owner=user, business=business) is None
    assert suggested_geo(db, owner=user, business=business).mode != "places"
    assert db.scalar(select(User)) is not None
    assert db.scalar(select(CampaignLaunch)) is None
