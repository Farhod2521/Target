"""TZ 2.4 and 2.5: another form, and a chat advert's greeting, on a running advert.

Either is saved one of two ways: in this advert (Meta reviews it again, likes
and comments start over) or as a new advert while this one stops.
"""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from adskit.dto import ActionResult, StatusDTO
from adskit.refs import ExternalRef
from fastapi.testclient import TestClient
from metaads import PROVIDER
from metaads import welcome as greeting
from metaads.launcher import MetaLauncher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.models import Ad, AdCreative
from app.modules.ads.services import page_forms, swap
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from app.modules.businesses.models import Business
from app.modules.integrations.models import PageAccount
from app.modules.leads.models import LeadForm
from tests.pg.test_ads_additions import _signed_in

# What Ads Manager writes, cut down: more than this product does, and a template.
SAVED = {
    "auto_follow_up": {"text": "Salom!"},
    "type": "VISUAL_EDITOR",
    "version": 2,
    "landing_screen_type": "welcome_message",
    "media_type": "text",
    "text_format": {
        "customer_action_type": "ice_breakers",
        "message": {
            "text": "Assalomu alaykum!",
            "ice_breakers": [{"title": "Narxi?", "response": "100 ming"}],
            "quick_replies": [],
        },
    },
    "image_format": {"message": {"text": "Assalomu alaykum!"}},
    "template_id": "1853199342343084",
}


def _story(db: Session, owner: Any, block: dict[str, Any]) -> None:
    creative = db.scalar(select(AdCreative).where(AdCreative.owner_id == owner.id))
    assert creative is not None
    creative.story_raw = {"page_id": "page_1", "link_data": block}
    db.commit()


def _chat(db: Session, owner: Any) -> None:
    _story(
        db,
        owner,
        {
            "message": "Buyurtma bering",
            "link": "https://tort.uz",
            "call_to_action": {
                "type": "MESSAGE_PAGE",
                "value": {"app_destination": "MESSENGER"},
            },
            "page_welcome_message": json.dumps(SAVED),
        },
    )


def _lead(db: Session, owner: Any) -> None:
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == owner.id))
    assert page is not None
    for external_id in ("f_1", "f_2"):
        db.add(
            LeadForm(
                owner_id=owner.id,
                provider=PROVIDER,
                external_id=external_id,
                page_id=page.id,
                name=f"Forma {external_id}",
                questions_raw=[{"key": "phone", "type": "PHONE"}],
            )
        )
    for ad in db.scalars(select(Ad).where(Ad.owner_id == owner.id)):
        ad.lead_form_external_id = "f_1"
    db.commit()
    _story(
        db,
        owner,
        {
            "message": "Buyurtma bering",
            "link": "https://tort.uz",
            "call_to_action": {
                "type": "SIGN_UP",
                "value": {"lead_gen_form_id": "f_1", "link": "https://tort.uz"},
            },
        },
    )


def _asked(db: Session, owner: Any) -> dict[str, Any]:
    log = db.scalar(
        select(ActionLog).where(
            ActionLog.owner_id == owner.id,
            ActionLog.action == ActionType.CREATIVE_SWAP,
        )
    )
    assert log is not None
    return dict(log.request_payload)


# -- the greeting, as Meta holds it --------------------------------------------------


def test_a_rewritten_greeting_keeps_what_it_did_not_touch() -> None:
    block = {"page_welcome_message": json.dumps(SAVED)}
    assert greeting.read(block).questions == (
        greeting.Question(title="Narxi?", response="100 ming"),
    )

    greeting.put(
        block,
        greeting.Welcome(
            text="Xush kelibsiz",
            questions=(
                greeting.Question(title="Narxi?", response="120 ming"),
                greeting.Question(title="Manzil?"),
            ),
        ),
    )

    found = json.loads(block["page_welcome_message"])
    assert found["auto_follow_up"] == {"text": "Salom!"}
    assert "template_id" not in found
    assert found["image_format"]["message"]["text"] == "Xush kelibsiz"
    assert found["text_format"]["message"]["ice_breakers"] == [
        {"title": "Narxi?", "response": "120 ming"},
        {"title": "Manzil?"},
    ]


def test_a_greeting_without_questions_goes_back_to_the_typed_line() -> None:
    block = {"page_welcome_message": json.dumps(SAVED)}

    greeting.put(block, greeting.Welcome(text="Salom"))

    found = json.loads(block["page_welcome_message"])
    assert found["text_format"]["customer_action_type"] == "autofill_message"
    assert "ice_breakers" not in found["text_format"]["message"]


def test_an_empty_greeting_lets_meta_write_its_own() -> None:
    block = {"page_welcome_message": json.dumps(SAVED)}

    greeting.put(block, greeting.Welcome(text=""))

    assert "page_welcome_message" not in block


# -- the screen ------------------------------------------------------------------------


def test_a_chat_advert_shows_its_greeting_and_saves_a_new_one(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _chat(db, owner)

    form = client.get("/api/v1/campaigns/ads/a_1/edit", headers=headers).json()
    assert form["welcome"]["text"] == "Assalomu alaykum!"
    assert form["welcome"]["questions"] == [{"title": "Narxi?", "response": "100 ming"}]
    assert form["welcome"]["maxQuestions"] == 4

    saved = client.post(
        "/api/v1/campaigns/ads/a_1/edit",
        json={
            "message": "Buyurtma bering",
            "welcome": {
                "text": "Assalomu alaykum!",
                "questions": [{"title": "Narxi?", "response": "120 ming"}],
            },
            "inPlace": True,
        },
        headers=headers,
    )

    assert saved.status_code == 200, saved.text
    asked = _asked(db, owner)
    assert asked["in_place"] is True
    assert asked["welcome"]["questions"] == [
        {"title": "Narxi?", "response": "120 ming"}
    ]


def test_too_many_questions_are_refused(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _chat(db, owner)

    answer = client.post(
        "/api/v1/campaigns/ads/a_1/edit",
        json={
            "message": "Buyurtma bering",
            "welcome": {"text": "Salom", "questions": [{"title": "?"}] * 5},
        },
        headers=headers,
    )

    assert answer.status_code == 422, answer.text
    assert db.scalar(select(ActionLog)) is None


def test_an_advert_that_opens_no_chat_has_no_greeting(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _lead(db, owner)

    form = client.get("/api/v1/campaigns/ads/a_1/edit", headers=headers).json()
    answer = client.post(
        "/api/v1/campaigns/ads/a_1/edit",
        json={"message": "Buyurtma bering", "welcome": {"text": "Salom"}},
        headers=headers,
    )

    assert form["welcome"] is None
    assert answer.status_code in (400, 409, 422), answer.text


def test_another_form_in_the_same_advert(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _lead(db, owner)

    form = client.get("/api/v1/campaigns/ads/a_1/edit", headers=headers).json()
    assert [row["id"] for row in form["forms"]["options"]] == ["f_2"]
    saved = client.post(
        "/api/v1/campaigns/ads/a_1/edit",
        json={"message": "Buyurtma bering", "leadForm": "f_2", "inPlace": True},
        headers=headers,
    )

    assert saved.status_code == 200, saved.text
    asked = _asked(db, owner)
    assert (asked["lead_form_id"], asked["in_place"]) == ("f_2", True)


# -- the writes ------------------------------------------------------------------------


class Port:
    def __init__(self) -> None:
        self.paused: list[str] = []

    def set_status(self, *, ref: ExternalRef, status: str, **_: Any) -> None:
        self.paused.append(ref.id)

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        return StatusDTO(ref=ref, status="ACTIVE", delivery="active")


@pytest.fixture
def launcher(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    def done(level: str, ref_id: str) -> ActionResult:
        return ActionResult(
            ok=True,
            ref=ExternalRef(provider=PROVIDER, level=level, id=ref_id),  # type: ignore[arg-type]
            dry_run=False,
        )

    def restage_creative(_self: Any, **kw: Any) -> ActionResult:
        calls.append(("creative", kw["story"]))
        return done("creative", "cr_new")

    def create_ad(_self: Any, **kw: Any) -> ActionResult:
        calls.append(("ad", kw))
        return done("ad", "ad_new")

    monkeypatch.setattr(MetaLauncher, "restage_creative", restage_creative)
    monkeypatch.setattr(MetaLauncher, "create_ad", create_ad)
    monkeypatch.setattr(
        swap,
        "set_creative",
        lambda **kw: calls.append(("set_creative", kw)) or True,
    )
    return calls


def _swapped(asked: dict[str, Any], story: dict[str, Any], port: Port) -> ActionResult:
    return swap._swap(
        log=SimpleNamespace(request_payload=asked, target_provider=PROVIDER),  # type: ignore[arg-type]
        target=SimpleNamespace(name="Reklama"),  # type: ignore[arg-type]
        story=story,
        account_id="act_1",
        adset_id="s_1",
        port=port,
        ref=ExternalRef(provider=PROVIDER, level="ad", id="a_1"),  # type: ignore[arg-type]
        before=StatusDTO(
            ref=ExternalRef(provider=PROVIDER, level="ad", id="a_1"),  # type: ignore[arg-type]
            status="ACTIVE",
            delivery="active",
        ),
        token="t",
        dry_run=False,
    )


LEAD_STORY = {
    "page_id": "page_1",
    "link_data": {
        "message": "Buyurtma bering",
        "call_to_action": {
            "type": "SIGN_UP",
            "value": {"lead_gen_form_id": "f_1"},
        },
    },
}


def test_in_place_the_advert_takes_the_new_creative_and_keeps_running(
    launcher: list[tuple[str, Any]],
) -> None:
    port = Port()

    done = _swapped({"lead_form_id": "f_2", "in_place": True}, LEAD_STORY, port)

    kinds = [kind for kind, _ in launcher]
    assert kinds == ["creative", "set_creative"]
    story = launcher[0][1]
    assert story["link_data"]["call_to_action"]["value"]["lead_gen_form_id"] == "f_2"
    assert launcher[1][1]["ad_id"] == "a_1"
    assert launcher[1][1]["creative_id"] == "cr_new"
    assert port.paused == []
    assert done.applied == {"creative": "cr_new", "in_place": True}


def test_as_a_new_advert_the_old_one_stops(launcher: list[tuple[str, Any]]) -> None:
    port = Port()

    _swapped({"lead_form_id": "f_2"}, LEAD_STORY, port)

    assert [kind for kind, _ in launcher] == ["creative", "ad"]
    assert port.paused == ["a_1"]


def test_a_greeting_reaches_the_new_creative(launcher: list[tuple[str, Any]]) -> None:
    story = {
        "page_id": "page_1",
        "link_data": {
            "message": "Yozing",
            "call_to_action": {
                "type": "MESSAGE_PAGE",
                "value": {"app_destination": "MESSENGER"},
            },
            "page_welcome_message": json.dumps(SAVED),
        },
    }
    asked = {
        "in_place": True,
        "welcome": {"text": "Salom", "questions": [{"title": "Narxi?"}]},
    }

    _swapped(asked, story, Port())

    sent = json.loads(launcher[0][1]["link_data"]["page_welcome_message"])
    assert sent["text_format"]["message"]["text"] == "Salom"
    assert sent["text_format"]["message"]["ice_breakers"] == [{"title": "Narxi?"}]


# -- a new form ------------------------------------------------------------------------


def test_a_new_form_is_made_on_the_adverts_page(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner, _campaign = _signed_in(client, db)
    _lead(db, owner)
    made: list[Any] = []

    def create(**kw: Any) -> str:
        made.append(kw)
        return "f_new"

    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == owner.id))
    db.add(
        Business(
            user_id=owner.id,
            page_id=page.id,  # type: ignore[union-attr]
            name="Bahor",
            timezone="Asia/Tashkent",
            country_code="UZ",
        )
    )
    db.commit()
    monkeypatch.setattr(page_forms, "create_lead_form", create)
    monkeypatch.setattr(page_forms, "_decrypted", lambda _page: "page-token")
    monkeypatch.setattr(page_forms.settings, "ads_dry_run", False)

    answer = client.post(
        "/api/v1/campaigns/ads/a_1/forms",
        json={"name": "Kuzgi forma", "questions": ["Qaysi filial?", " "]},
        headers=headers,
    )

    assert answer.status_code == 200, answer.text
    assert answer.json() == {"id": "f_new", "name": "Kuzgi forma"}
    spec = made[0]["spec"]
    assert [row.kind for row in spec.questions] == ["FULL_NAME", "PHONE", "CUSTOM"]
    assert spec.questions[2].label == "Qaysi filial?"
    assert made[0]["page_token"] == "page-token"
    form = client.get("/api/v1/campaigns/ads/a_1/edit", headers=headers).json()
    assert "f_new" in [row["id"] for row in form["forms"]["options"]]
