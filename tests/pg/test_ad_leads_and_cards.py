"""A running advert's button, address, tracking tags and carousel cards, against PostgreSQL."""

from types import SimpleNamespace
from typing import Any

import pytest
from adskit.dto import ActionResult, StatusDTO
from adskit.refs import ExternalRef
from fastapi.testclient import TestClient
from metaads import PROVIDER
from metaads.launcher import MetaLauncher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.models import ChatTemplate, MediaAsset
from app.modules.ads.services import additions, copies, swap
from app.modules.integrations.models import PageAccount
from app.modules.leads.models import LeadForm
from tests.pg.test_ad_form_and_greeting import _asked, _chat, _lead, _story
from tests.pg.test_ads_additions import _signed_in

URL = "/api/v1/campaigns/ads/a_1/edit"
SITE = "https://tort.uz"
BUTTON = {"type": "LEARN_MORE", "value": {"link": SITE}}
WORDS = {"message": "Buyurtma bering", "headline": "", "description": ""}


def _site(db: Session, owner: Any) -> None:
    _story(
        db,
        owner,
        {"message": "Buyurtma bering", "link": SITE, "call_to_action": BUTTON},
    )


def _carousel(db: Session, owner: Any) -> None:
    _story(
        db,
        owner,
        {
            "message": "Buyurtma bering",
            "link": SITE,
            "call_to_action": BUTTON,
            "child_attachments": [
                {"name": "Asal", "image_hash": "hash_1", "link": SITE},
                {"name": "Napoleon", "image_hash": "h2", "link": SITE},
                {"name": "Film", "video_id": "v9", "picture": "https://cdn/p.jpg"},
            ],
        },
    )


def _picture(db: Session, owner: Any) -> str:
    asset = db.scalar(select(MediaAsset).where(MediaAsset.owner_id == owner.id))
    assert asset is not None
    return str(asset.id)


def test_the_form_says_where_the_advert_leads_and_what_its_button_may_say(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _site(db, owner)

    form = client.get(URL, headers=headers).json()

    assert form["link"] == SITE
    assert form["button"] == "LEARN_MORE"
    keys = [row["key"] for row in form["buttons"]]
    assert keys[0] == "LEARN_MORE" and "SHOP_NOW" in keys
    assert all(row["label"] for row in form["buttons"])
    assert form["urlTags"]["value"] == ""
    assert "utm_source" in form["urlTags"]["suggested"]
    assert form["cards"] is None and form["welcomeTemplates"] == []


def test_a_form_advert_has_no_address_to_change_and_offers_its_own_questions(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _lead(db, owner)
    held = db.scalar(select(LeadForm).where(LeadForm.external_id == "f_1"))
    assert held is not None
    held.questions_raw = [
        {"type": "PHONE"},
        {"type": "CUSTOM", "key": "q1", "label": "Qaysi tort?"},
    ]
    db.commit()

    form = client.get(URL, headers=headers).json()
    refused = client.post(
        URL, json={**WORDS, "link": "https://boshqa.uz"}, headers=headers
    )

    assert form["link"] is None and form["urlTags"] is None
    assert form["forms"]["currentId"] == "f_1"
    assert form["forms"]["currentQuestions"] == ["Qaysi tort?"]
    assert "SIGN_UP" in [row["key"] for row in form["buttons"]]
    assert refused.status_code == 400 and "saytga olib bormaydi" in refused.text


def test_another_word_another_address_and_other_tags_are_asked_for(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _site(db, owner)

    saved = client.post(
        URL,
        json={
            **WORDS,
            "button": "SHOP_NOW",
            "link": "tort.uz/menyu",
            "urlTags": "?utm_source=meta&utm_medium=cpc",
        },
        headers=headers,
    )

    assert saved.status_code == 200, saved.text
    asked = _asked(db, owner)
    assert asked["button"] == "SHOP_NOW"
    assert asked["link"] == "https://tort.uz/menyu"
    assert asked["url_tags"] == "utm_source=meta&utm_medium=cpc"


def test_what_is_sent_back_as_it_is_makes_no_new_advert(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _site(db, owner)

    same = client.post(
        URL,
        json={**WORDS, "button": "LEARN_MORE", "link": SITE, "urlTags": ""},
        headers=headers,
    )

    assert same.status_code == 400 and "Hech narsa o'zgarmadi" in same.text


@pytest.mark.parametrize(
    ("sent", "said"),
    [
        ({"button": "CALL_NOW"}, "bunday tugma"),
        ({"link": "instagram.com/tort"}, "o'z saytingiz"),
        ({"link": "bu sayt emas"}, "Sayt manzilini"),
        ({"urlTags": "utm source=meta"}, "Manzil parametrlari"),
    ],
)
def test_what_cannot_be_sent_is_refused_in_words(
    client: TestClient, db: Session, queued: list, sent: dict[str, str], said: str
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _site(db, owner)

    refused = client.post(URL, json={**WORDS, **sent}, headers=headers)

    assert refused.status_code in (400, 422), refused.text
    assert said in refused.text


def test_a_carousel_shows_its_cards_and_they_are_moved_and_added_to(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _carousel(db, owner)
    picture = _picture(db, owner)

    form = client.get(URL, headers=headers).json()
    saved = client.post(
        URL,
        json={
            **WORDS,
            "cards": [
                {"source": 1, "headline": "Napoleon 20%"},
                {"source": 0},
                {"headline": "Medovik", "picture": picture},
            ],
        },
        headers=headers,
    )

    assert [card["headline"] for card in form["cards"]] == ["Asal", "Napoleon", "Film"]
    assert form["cards"][2] == {
        "source": 2,
        "headline": "Film",
        "description": "",
        "thumb": "https://cdn/p.jpg",
        "isVideo": True,
    }
    assert form["cardLimits"]["min"] == 2 and form["cardLimits"]["max"] == 10
    assert saved.status_code == 200, saved.text
    assert _asked(db, owner)["cards"] == [
        {
            "source": 1,
            "headline": "Napoleon 20%",
            "description": None,
            "image_hash": "",
        },
        {"source": 0, "headline": None, "description": None, "image_hash": ""},
        {
            "source": None,
            "headline": "Medovik",
            "description": None,
            "image_hash": "hash_1",
        },
    ]


def test_cards_that_cannot_be_built_are_refused(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _carousel(db, owner)

    one = client.post(URL, json={**WORDS, "cards": [{"source": 0}]}, headers=headers)
    bare = client.post(
        URL,
        json={**WORDS, "cards": [{"source": 0}, {"headline": "rasmsiz"}]},
        headers=headers,
    )
    foreign = client.post(
        URL,
        json={
            **WORDS,
            "cards": [
                {"source": 0},
                {"picture": "00000000-0000-0000-0000-000000000000"},
            ],
        },
        headers=headers,
    )
    same = client.post(
        URL,
        json={**WORDS, "cards": [{"source": 0}, {"source": 1}, {"source": 2}]},
        headers=headers,
    )

    assert one.status_code == 400 and "2 tadan 10 tagacha" in one.text
    assert bare.status_code == 400 and "rasm kerak" in bare.text
    assert foreign.status_code == 422 and "kutubxonadagi rasm" in foreign.text
    assert same.status_code == 400 and "Hech narsa o'zgarmadi" in same.text


def test_cards_on_an_advert_that_is_not_a_carousel_are_refused(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _site(db, owner)

    refused = client.post(
        URL, json={**WORDS, "cards": [{"source": 0}, {"source": 1}]}, headers=headers
    )

    assert refused.status_code == 400 and "karusel emas" in refused.text


def test_a_chat_advert_is_offered_the_greetings_kept_for_its_page(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _chat(db, owner)
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == owner.id))
    assert page is not None
    page.external_id = "page_1"
    db.add(
        ChatTemplate(
            owner_id=owner.id,
            page_id=page.id,
            name="Bahor",
            welcome_text="Salom!",
            questions=["Narxi?", "Manzil?"],
            answers=["100 ming"],
        )
    )
    db.commit()

    form = client.get(URL, headers=headers).json()

    assert form["link"] is None
    assert [
        {key: row[key] for key in ("name", "text", "questions")}
        for row in form["welcomeTemplates"]
    ] == [
        {
            "name": "Bahor",
            "text": "Salom!",
            "questions": [
                {"title": "Narxi?", "response": "100 ming"},
                {"title": "Manzil?", "response": ""},
            ],
        }
    ]


# -- the write: what reaches Meta ---------------------------------------------------


class Port:
    def __init__(self) -> None:
        self.paused: list[str] = []

    def set_status(self, *, ref: ExternalRef, **_: Any) -> ActionResult:
        self.paused.append(ref.id)
        return ActionResult(ok=True, ref=ref, dry_run=False)

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        return StatusDTO(ref=ref, status="ACTIVE", delivery="active")


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def done(level: str, ref_id: str) -> ActionResult:
        return ActionResult(
            ok=True,
            ref=ExternalRef(provider=PROVIDER, level=level, id=ref_id),  # type: ignore[arg-type]
            dry_run=False,
        )

    def restage_creative(_self: Any, **kw: Any) -> ActionResult:
        calls.append(kw)
        return done("creative", "cr_new")

    monkeypatch.setattr(MetaLauncher, "restage_creative", restage_creative)
    monkeypatch.setattr(
        MetaLauncher, "create_ad", lambda _s, **kw: done("ad", "ad_new")
    )
    for module in (swap, copies, additions):
        assert module.tags_to_carry is swap.tags_to_carry
    monkeypatch.setattr(
        MetaLauncher, "creative_url_tags", lambda _s, **kw: "utm_source=held"
    )
    return calls


def _swapped(asked: dict[str, Any], story: dict[str, Any]) -> None:
    ref = ExternalRef(provider=PROVIDER, level="ad", id="a_1")  # type: ignore[arg-type]
    swap._swap(
        log=SimpleNamespace(request_payload=asked, target_provider=PROVIDER),  # type: ignore[arg-type]
        target=SimpleNamespace(name="Reklama", creative_external_id="cr_1"),  # type: ignore[arg-type]
        story=story,
        account_id="act_1",
        adset_id="s_1",
        port=Port(),
        ref=ref,
        before=StatusDTO(ref=ref, status="ACTIVE", delivery="active"),
        token="t",
        dry_run=False,
    )


STORY = {
    "page_id": "page_1",
    "link_data": {"message": "Buyurtma bering", "link": SITE, "call_to_action": BUTTON},
}


def test_the_next_creative_keeps_the_tags_nobody_changed(
    made: list[dict[str, Any]],
) -> None:
    _swapped({"message": "Yangi matn"}, STORY)

    assert made[0]["url_tags"] == "utm_source=held"
    assert made[0]["story"]["link_data"]["message"] == "Yangi matn"


def test_tags_that_were_changed_or_removed_are_the_ones_sent(
    made: list[dict[str, Any]],
) -> None:
    _swapped({"url_tags": "utm_source=meta"}, STORY)
    _swapped({"url_tags": ""}, STORY)

    assert [call["url_tags"] for call in made] == ["utm_source=meta", ""]


def test_the_word_and_the_address_reach_the_new_creative(
    made: list[dict[str, Any]],
) -> None:
    _swapped({"button": "SHOP_NOW", "link": "https://tort.uz/menyu"}, STORY)

    block = made[0]["story"]["link_data"]
    assert block["link"] == "https://tort.uz/menyu"
    assert block["call_to_action"] == {
        "type": "SHOP_NOW",
        "value": {"link": "https://tort.uz/menyu"},
    }


def test_tags_that_cannot_be_read_do_not_stop_the_change(
    made: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from adskit.errors import ProviderError

    def broken(_self: Any, **_: Any) -> str:
        raise ProviderError("down")

    monkeypatch.setattr(MetaLauncher, "creative_url_tags", broken)

    _swapped({"message": "Yangi matn"}, STORY)

    assert made[0]["url_tags"] == ""
