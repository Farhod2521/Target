"""The changes the assistant prepares beyond a budget and a switch, against PostgreSQL.

Each is the campaigns screen's own change, behind a confirm button: nothing
is sent until the owner presses, and the press reads the object again.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdCreative, AdSet
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from app.modules.chat import services
from tests.pg.conftest import sign_up
from tests.pg.test_chat import _account, _desk, _mirror

STORY = {
    "page_id": "page_1",
    "link_data": {
        "message": "Buyurtma bering",
        "name": "Bahorgi tort",
        "link": "https://bahor.example",
        "call_to_action": {
            "type": "LEARN_MORE",
            "value": {"link": "https://bahor.example"},
        },
    },
}


def _ready(client: TestClient, db: Session) -> tuple[dict[str, str], User]:
    headers = sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)
    creative = db.scalars(select(AdCreative)).one()
    creative.story_raw = STORY
    db.commit()
    return headers, owner


def _ask(desk: Any, **arguments: Any) -> Any:
    from llmkit import ToolCall

    from core.chat.lookup_arguments import ChangeProposal

    return desk(
        ToolCall(id="t1", name="propose_change", arguments=ChangeProposal(**arguments))
    )


def _pressed(
    client: TestClient, db: Session, headers: dict[str, str], desk: Any
) -> ActionLog:
    """Store the answer with its buttons, press the first, and return what was opened."""
    from app.modules.chat.services.answer import _store

    asked = client.post(
        "/api/v1/chat/ask", json={"question": "O'zgartir"}, headers=headers
    )
    payload = services.turn_payload(turn_id=asked.json()["turn_id"])
    assert payload is not None
    _store(
        db,
        payload=payload,
        text="Tayyorladim.",
        gate=desk.gate,
        choices=desk.changes,
        now=utcnow(),
    )
    db.commit()
    pressed = client.post(
        f"/api/v1/chat/changes/{payload['message_id']}/P1", headers=headers
    )
    assert pressed.json()["state"] == "working", pressed.text
    # The thread still draws the button, without the wish kept for the press.
    thread = client.get(
        f"/api/v1/chat/threads/{asked.json()['session_id']}", headers=headers
    )
    assert thread.status_code == 200, thread.text
    shown = thread.json()["messages"][-1]["changes"][0]
    assert "params" not in shown and shown["before"] and shown["after"]
    return db.scalars(select(ActionLog)).one()


def test_a_group_is_renamed_from_the_conversation(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner = _ready(client, db)
    desk = _desk(db, owner)

    empty = _ask(desk, action="rename", level="adset", object_id="s_1")
    prepared = _ask(
        desk, action="rename", level="adset", object_id="s_1", name="  Yoshlar  18-30 "
    )

    assert empty.is_error and "needs the new name" in empty.text
    assert not prepared.is_error, prepared.text
    item = desk.changes[0]
    assert (item["before"], item["after"]) == ("Toshkent 25-45", "Yoshlar 18-30")
    assert item["label"] == "Nomini o'zgartirish"
    assert item["target_kind"] == "reklama guruhi"
    assert db.scalar(select(ActionLog.id)) is None
    log = _pressed(client, db, headers, desk)
    assert log.action == ActionType.NAME_SET and log.target_level == "adset"
    assert log.request_payload["name"] == "Yoshlar 18-30"


def test_an_end_date_is_set_and_taken_off(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner = _ready(client, db)
    desk = _desk(db, owner)
    soon = (utcnow() + timedelta(days=10)).date()

    past = _ask(
        desk, action="end_date", level="adset", object_id="s_1", end_date="2020-01-01"
    )
    wrong = _ask(
        desk,
        action="end_date",
        level="campaign",
        object_id="c_1",
        end_date=soon.isoformat(),
    )
    none = _ask(desk, action="no_end_date", level="adset", object_id="s_1")
    prepared = _ask(
        desk,
        action="end_date",
        level="adset",
        object_id="s_1",
        end_date=soon.isoformat(),
    )

    assert past.is_error and "tomorrow or later" in past.text
    assert wrong.is_error and "ad group" in wrong.text
    assert none.is_error and "no end date already" in none.text
    assert not prepared.is_error, prepared.text
    item = desk.changes[0]
    assert item["before"] == "Tugash sanasi yo'q"
    assert item["after"] == soon.strftime("%d.%m.%Y")
    log = _pressed(client, db, headers, desk)
    assert log.action == ActionType.END_TIME_SET
    assert log.request_payload["end_time"].startswith(soon.isoformat())


def test_an_end_date_that_is_there_is_taken_off(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner = _ready(client, db)
    group = db.scalars(select(AdSet)).one()
    group.end_time = datetime(2030, 1, 31, 18, 59, 59, tzinfo=UTC)
    db.commit()
    desk = _desk(db, owner)

    prepared = _ask(desk, action="no_end_date", level="adset", object_id="s_1")

    assert not prepared.is_error, prepared.text
    assert desk.changes[0]["after"] == "Tugash sanasi yo'q"
    log = _pressed(client, db, headers, desk)
    assert log.request_payload["end_time"] == ""


def test_an_audience_is_changed_by_age_gender_and_the_widening(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner = _ready(client, db)
    desk = _desk(db, owner)

    bare = _ask(desk, action="audience", level="adset", object_id="s_1")
    same = _ask(
        desk, action="audience", level="adset", object_id="s_1", age_min=25, age_max=45
    )
    prepared = _ask(
        desk,
        action="audience",
        level="adset",
        object_id="s_1",
        age_max=35,
        gender="women",
    )

    assert bare.is_error and "Reklama screen" in bare.text
    assert same.is_error and "already like that" in same.text
    assert not prepared.is_error, prepared.text
    item = desk.changes[0]
    assert item["before"] == "25-45 yosh, hamma, Advantage+ o'chirilgan"
    assert item["after"] == "25-35 yosh, ayollar, Advantage+ o'chirilgan"
    assert item["params"] == {
        "age_min": None,
        "age_max": 35,
        "gender": "women",
        "advantage": "",
    }
    log = _pressed(client, db, headers, desk)
    assert log.action == ActionType.TARGETING_SWAP
    targeting = log.request_payload["targeting"]
    assert (targeting["age_min"], targeting["age_max"], targeting["genders"]) == (
        25,
        35,
        [2],
    )
    assert targeting["geo_locations"] == {"countries": ["UZ"]}


def test_the_press_reads_the_audience_as_it_stands_then(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner = _ready(client, db)
    desk = _desk(db, owner)
    _ask(desk, action="audience", level="adset", object_id="s_1", advantage="on")
    assert desk.changes[0]["after"] == "25-65+ yosh, hamma, Advantage+ yoqilgan"
    group = db.scalars(select(AdSet)).one()
    group.targeting_raw = {**group.targeting_raw, "locales": [6]}
    db.commit()

    log = _pressed(client, db, headers, desk)

    targeting = log.request_payload["targeting"]
    assert targeting["locales"] == [6]
    assert targeting["targeting_automation"] == {"advantage_audience": 1}


def test_a_learning_group_keeps_its_audience_and_says_why(
    client: TestClient, db: Session, queued: list
) -> None:
    _headers, owner = _ready(client, db)
    group = db.scalars(select(AdSet)).one()
    group.is_learning = True
    db.commit()
    desk = _desk(db, owner)

    refused = _ask(
        desk, action="audience", level="adset", object_id="s_1", gender="men"
    )

    assert refused.is_error and "the product refuses it" in refused.text
    assert desk.changes == []


def test_where_it_is_shown_is_changed_and_a_profile_visit_is_not(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner = _ready(client, db)
    desk = _desk(db, owner)

    prepared = _ask(
        desk, action="placement", level="adset", object_id="s_1", apps="fbig"
    )

    assert not prepared.is_error, prepared.text
    item = desk.changes[0]
    assert item["before"] == "Meta o'zi tanlaydi"
    assert item["after"] == "Faqat Facebook va Instagram"
    log = _pressed(client, db, headers, desk)
    assert log.request_payload["targeting"]["publisher_platforms"] == [
        "facebook",
        "instagram",
    ]
    group = db.scalars(select(AdSet)).one()
    group.destination_type_raw = "INSTAGRAM_PROFILE"
    db.commit()
    pinned = _ask(
        _desk(db, owner),
        action="placement",
        level="adset",
        object_id="s_1",
        apps="facebook",
    )
    assert pinned.is_error and "Instagram only" in pinned.text


def test_a_price_ceiling_is_set(client: TestClient, db: Session, queued: list) -> None:
    headers, owner = _ready(client, db)
    group = db.scalars(select(AdSet)).one()
    group.currency = "USD"
    db.commit()
    desk = _desk(db, owner)

    bare = _ask(desk, action="cost_cap", level="adset", object_id="s_1")
    high = _ask(desk, action="cost_cap", level="adset", object_id="s_1", cost_cap="9")
    none = _ask(desk, action="cost_cap", level="adset", object_id="s_1", cost_cap="0")
    prepared = _ask(
        desk, action="cost_cap", level="adset", object_id="s_1", cost_cap="2,5"
    )

    assert bare.is_error and "needs the amount" in bare.text
    assert high.is_error and "the product refuses it" in high.text
    assert none.is_error and "already its price ceiling" in none.text
    assert not prepared.is_error, prepared.text
    item = desk.changes[0]
    assert item["before"] == "Chegara yo'q" and "2" in item["after"]
    log = _pressed(client, db, headers, desk)
    assert log.action == ActionType.DELIVERY_SET
    assert log.request_payload["cap_minor"] == 250


def test_an_adverts_words_button_and_address_are_changed(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner = _ready(client, db)
    desk = _desk(db, owner)

    same = _ask(
        desk,
        action="advert_text",
        level="ad",
        object_id="a_1",
        message="Buyurtma bering",
    )
    foreign = _ask(
        desk, action="advert_text", level="ad", object_id="a_1", link="instagram.com/x"
    )
    button = _ask(
        desk, action="advert_text", level="ad", object_id="a_1", button="call_now"
    )
    prepared = _ask(
        desk,
        action="advert_text",
        level="ad",
        object_id="a_1",
        message="Bugun 20% chegirma",
        button="shop_now",
        link="bahor.example/menyu",
    )

    assert same.is_error and "must differ" in same.text
    assert foreign.is_error and "address cannot be used" in foreign.text
    assert button.is_error and "the product refuses it" in button.text
    assert not prepared.is_error, prepared.text
    item = desk.changes[0]
    assert item["before"] == (
        "Matn: Buyurtma bering\nTugma: Batafsil\nHavola: https://bahor.example"
    )
    assert item["after"] == (
        "Matn: Bugun 20% chegirma\nTugma: Xarid qilish\n"
        "Havola: https://bahor.example/menyu"
    )
    log = _pressed(client, db, headers, desk)
    assert log.action == ActionType.CREATIVE_SWAP
    asked = log.request_payload
    assert asked["message"] == "Bugun 20% chegirma"
    assert asked["button"] == "SHOP_NOW"
    assert asked["link"] == "https://bahor.example/menyu"
    assert asked["headline"] is None and asked["in_place"] is False


def test_an_advert_that_shows_a_post_keeps_its_words(
    client: TestClient, db: Session, queued: list
) -> None:
    _headers, owner = _ready(client, db)
    creative = db.scalars(select(AdCreative)).one()
    creative.story_raw = {}
    db.commit()

    refused = _ask(
        _desk(db, owner),
        action="advert_text",
        level="ad",
        object_id="a_1",
        message="Yangi",
    )

    assert refused.is_error and "live on the post" in refused.text


def test_a_button_whose_object_is_gone_goes_and_sends_nothing(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.chat.services.answer import _store

    headers, owner = _ready(client, db)
    desk = _desk(db, owner)
    _ask(desk, action="rename", level="ad", object_id="a_1", name="Video 1")
    asked = client.post("/api/v1/chat/ask", json={"question": "Nom"}, headers=headers)
    payload = services.turn_payload(turn_id=asked.json()["turn_id"])
    assert payload is not None
    _store(
        db,
        payload=payload,
        text="Tayyor.",
        gate=desk.gate,
        choices=desk.changes,
        now=utcnow(),
    )
    db.delete(db.scalars(select(Ad)).one())
    db.commit()

    pressed = client.post(
        f"/api/v1/chat/changes/{payload['message_id']}/P1", headers=headers
    )

    assert pressed.json()["state"] == "gone"
    assert db.scalar(select(ActionLog.id)) is None


def test_the_newer_assistants_button_carries_out_the_same_change(
    client: TestClient, db: Session, queued: list
) -> None:
    """Its press has its own code: a kind it did not know once became a switch-on."""
    from app.modules.assistant.models import AssistantMessage, AssistantSession
    from app.modules.assistant.services import buttons

    _headers, owner = _ready(client, db)
    desk = _desk(db, owner)
    _ask(desk, action="rename", level="adset", object_id="s_1", name="Yoshlar")
    session = AssistantSession(owner_id=owner.id)
    db.add(session)
    db.flush()
    row = AssistantMessage(
        owner_id=owner.id,
        session_id=session.id,
        author="ai",
        text="Tayyor.",
        buttons=[dict(desk.changes[0])],
    )
    db.add(row)
    db.commit()

    pressed = buttons.press(
        db, owner=owner, message_id=str(row.id), key="P1", now=utcnow()
    )
    db.commit()

    assert pressed.state == "working", pressed.text
    log = db.scalars(select(ActionLog)).one()
    assert log.action == ActionType.NAME_SET
    assert log.request_payload["name"] == "Yoshlar"
