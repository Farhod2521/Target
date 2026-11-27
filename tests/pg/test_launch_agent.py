"""The advert chat over HTTP: it opens the wizard's own launch, asks only
what is missing, reads typed words with one model call, saves through the
wizard's check, and settles the business's kind on the way."""

from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from llmkit import LLMError, LLMResult
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.audit.models import LLMCall
from app.modules.businesses.constants import TypeState
from app.modules.businesses.models import Business, BusinessCategory
from app.modules.businesses.selectors.knowledge import known
from app.modules.launch_agent import constants
from app.modules.launch_agent.models import LaunchAgentSession
from app.modules.launch_agent.services import hear, stages
from core.launch_agent.heard import HeardOut
from tests.pg.conftest import sign_up
from tests.pg.test_launch_api import _ready

URL = "/api/v3/launch-agent/sessions"


def _model(
    monkeypatch: pytest.MonkeyPatch, *answers: HeardOut | Exception
) -> list[dict]:
    """A model that fills the form from a script; answers what it was asked."""
    asked: list[dict[str, Any]] = []
    left = list(answers)

    class Fake:
        def structured(self, **ask: Any) -> LLMResult[HeardOut]:
            asked.append(ask)
            answer = left.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return LLMResult(
                value=answer,
                input_tokens=400,
                output_tokens=30,
                cost_micros=1,
                currency="USD",
                latency_ms=1,
                prompt_name=ask.get("prompt_name", ""),
                prompt_version=ask.get("prompt_version", ""),
                model="test",
            )

    @contextmanager
    def factory(**_: Any):  # type: ignore[no-untyped-def]
        yield Fake()

    monkeypatch.setattr(hear, "claude", factory)
    return asked


def _floor(db: Session, user: User, minor: int = 100) -> None:
    """Give the owner's ad account the daily minimum Meta reports for it."""
    from app.modules.integrations.models import AdAccount

    account = db.scalars(select(AdAccount).where(AdAccount.owner_id == user.id)).one()
    account.min_daily_budget_minor = minor
    db.commit()


def _open(client: TestClient, auth: dict[str, str]) -> dict[str, Any]:
    opened = client.post(URL, headers=auth)
    assert opened.status_code == 200, opened.text
    return opened.json()  # type: ignore[no-any-return]


def _turn(
    client: TestClient, auth: dict[str, str], session: str, **body: str
) -> dict[str, Any]:
    answer = client.post(f"{URL}/{session}/turns", json=body, headers=auth)
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


def _press(
    client: TestClient, auth: dict[str, str], state: dict[str, Any], value: str
) -> dict[str, Any]:
    option = next(one for one in state["ask"]["options"] if one["value"] == value)
    return _turn(
        client, auth, state["session_id"], slot=option["slot"], value=option["value"]
    )


def test_buttons_alone_fill_the_launch_and_no_model_is_asked(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    _floor(db, user)
    asked = _model(monkeypatch, HeardOut(offer="IELTS kursi, oyiga 600 000 so'm"))

    state = _open(client, auth)
    assert state["status"] == "open" and state["ready"] is False
    assert state["ask"]["slot"] == "offer"
    assert state["messages"][0]["author"] == "agent"

    state = _turn(
        client, auth, state["session_id"], text="IELTS kursi, oyiga 600 000 so'm"
    )
    assert state["ask"]["slot"] == "goal"
    goals = [option["value"] for option in state["ask"]["options"]]
    assert "views" in goals
    # Nothing is recommended until the office writes its advice.
    assert not any(option["recommended"] for option in state["ask"]["options"])
    assert state["lines"] == []

    state = _press(client, auth, state, "views")
    assert state["ask"]["slot"] == "budget"
    assert state["ask"]["input"] == "money"
    # The sums offered are the first screen's own presets.
    assert [option["label"] for option in state["ask"]["options"]] == [
        "$2",
        "$5",
        "$10",
        "$20",
    ]

    state = _press(client, auth, state, "5.00")

    assert state["ready"] is True and state["status"] == "ready"
    # The questions are answered: the chat goes on to the pictures.
    assert (state["stage"], state["next"], state["wait"]) == ("media", "media", False)
    assert state["ask"]["slot"] == "media"
    assert [option["opens"] for option in state["ask"]["options"]] == [
        "media",
        "upload",
    ]
    assert state["lines"] == []
    assert [chip["slot"] for chip in state["chips"]][-3:] == ["offer", "goal", "budget"]
    # One typed message, one model call; the two presses cost none.
    assert len(asked) == 1
    assert len(db.scalars(select(LLMCall)).all()) == 1

    db.expire_all()
    launch = db.get(CampaignLaunch, state["launch_id"])
    assert launch is not None and launch.owner_id == user.id
    assert launch.answers["goal"] == "views"
    assert launch.answers["offer_text"] == "IELTS kursi, oyiga 600 000 so'm"
    assert launch.answers["daily_budget_minor"] > 0
    # The wizard's own screen reads the same launch.
    plan = client.get(f"/api/v1/launch/{launch.id}/plan", headers=auth)
    assert plan.status_code == 200, plan.text


def test_one_message_that_says_everything_is_ready_at_once(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, _user = _ready(client, db)
    asked = _model(
        monkeypatch,
        HeardOut(
            offer="Yozgi chegirma",
            goal="traffic",
            link="bahor.uz",
            budget="5",
            budget_currency="USD",
        ),
    )
    state = _open(client, auth)

    state = _turn(
        client,
        auth,
        state["session_id"],
        text="Yozgi chegirmani saytga yo'naltiramiz, bahor.uz, kuniga 5 dollar",
    )

    assert state["ready"] is True
    launch = db.get(CampaignLaunch, state["launch_id"])
    assert launch is not None
    assert launch.answers["link_url"].startswith("https://bahor.uz")
    assert launch.answers["daily_budget_minor"] == 500
    # The model was told the goals and the question it was answering.
    (ask,) = asked
    assert "- traffic - " in ask["system_tail"]
    assert "(field: offer)" in ask["system_tail"]
    assert "{{" not in ask["system_tail"]


def test_a_bare_sum_or_address_is_read_without_the_model(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, _user = _ready(client, db)
    asked = _model(
        monkeypatch, HeardOut(offer="Yozgi chegirma", goal="traffic"), HeardOut()
    )
    state = _open(client, auth)
    state = _turn(client, auth, state["session_id"], text="Yozgi chegirma, saytga")
    assert state["ask"]["slot"] == "link"

    wrong = _turn(client, auth, state["session_id"], text="bahor")
    # Not an address: the model is asked what else it could be - here, nothing.
    assert wrong["ask"]["slot"] == "link"

    state = _turn(client, auth, state["session_id"], text="bahor.uz")
    assert state["ask"]["slot"] == "budget"
    state = _turn(client, auth, state["session_id"], text="7$")

    assert state["ready"] is True
    assert [chip["value"] for chip in state["chips"]][-1] == "$7"
    assert len(asked) == 2  # the first message, and «bahor»


def test_a_budget_under_the_floor_is_asked_again_with_the_floor(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    _floor(db, user)
    _model(monkeypatch, HeardOut(offer="Yozgi chegirma", goal="views"))
    state = _open(client, auth)
    state = _turn(client, auth, state["session_id"], text="Yozgi chegirma, ko'rishsin")

    low = _turn(client, auth, state["session_id"], text="0.1")

    assert low["ready"] is False and low["ask"]["slot"] == "budget"
    assert low["lines"][0].startswith("Bu maqsad uchun kunlik byudjet kamida ")


def test_what_the_wizard_refuses_is_asked_again_in_its_words(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, _user = _ready(client, db)
    _model(
        monkeypatch,
        HeardOut(offer="Kafe", goal="traffic", link="instagram.com/bahor", budget="5"),
    )
    state = _open(client, auth)

    state = _turn(client, auth, state["session_id"], text="Kafe, instagramga, 5 dollar")

    # A Meta address is not a site of one's own: the wizard's check says so.
    assert state["ready"] is False
    assert state["ask"]["slot"] == "link"
    assert state["lines"]
    launch = db.get(CampaignLaunch, state["launch_id"])
    assert launch is not None and "link_url" not in (launch.answers or {})


def test_a_model_that_cannot_be_reached_says_it_did_not_understand(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, _user = _ready(client, db)
    _model(monkeypatch, LLMError("down"))
    state = _open(client, auth)

    state = _turn(client, auth, state["session_id"], text="Yozgi chegirma")

    assert state["lines"] == ["Buni tushunmadim, qaytadan yozib bering."]
    assert state["ask"]["slot"] == "offer"


def test_a_business_nobody_described_is_asked_and_its_kind_settled(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    business = db.scalars(select(Business).where(Business.user_id == user.id)).one()
    business.direction_id = None
    business.custom_category_id = None
    education = BusinessCategory(
        key="education", label_uz="Ta'lim", preset_key="education"
    )
    db.add(education)
    db.commit()
    asked = _model(
        monkeypatch,
        HeardOut(
            kind="Ingliz tili o'quv markazimiz bor",
            kind_direction="education",
            kind_subtype="ingliz tili kurslari",
        ),
        HeardOut(offer="IELTS kursi", goal="views", budget="5"),
    )

    state = _open(client, auth)
    assert state["ask"]["slot"] == "kind"

    state = _turn(
        client, auth, state["session_id"], text="Ingliz tili o'quv markazimiz bor"
    )

    assert "## Kinds of business" in asked[0]["system_tail"]
    assert state["ask"]["slot"] == "offer"
    assert state["chips"][0] == {
        "slot": "kind",
        "label": "Biznes",
        "value": "Ta'lim → ingliz tili kurslari",
    }
    db.expire_all()
    assert known(db, business).type_state == TypeState.GUESSED

    state = _turn(client, auth, state["session_id"], text="IELTS kursi, ko'rishsin, 5$")

    assert state["ready"] is True
    # The kind list is not sent once the kind is known.
    assert "## Kinds of business" not in asked[1]["system_tail"]
    db.expire_all()
    view = known(db, business)
    # Carrying on past the summary is their yes.
    assert view.type_state == TypeState.CONFIRMED
    assert view.direction is not None and view.direction.key == "education"
    assert view.does == "Ingliz tili o'quv markazimiz bor"


def test_an_open_conversation_is_carried_on_and_a_closed_one_is_not(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, _user = _ready(client, db)
    _model(monkeypatch, HeardOut(offer="Yozgi chegirma"))
    first = _open(client, auth)
    _turn(client, auth, first["session_id"], text="Yozgi chegirma")

    again = _open(client, auth)
    assert again["session_id"] == first["session_id"]
    assert again["ask"]["slot"] == "goal"
    read = client.get(f"{URL}/{first['session_id']}", headers=auth).json()
    assert read["ask"]["slot"] == "goal" and len(read["messages"]) == 3

    assert (
        client.post(f"{URL}/{first['session_id']}/close", headers=auth).status_code
        == 204
    )
    refused = client.post(
        f"{URL}/{first['session_id']}/turns", json={"text": "5"}, headers=auth
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "launch_agent_session_closed"
    fresh = _open(client, auth)
    assert fresh["session_id"] != first["session_id"]


def test_limits_and_strangers(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    _model(monkeypatch, HeardOut(offer="x"))
    state = _open(client, auth)
    session = db.get(LaunchAgentSession, state["session_id"])
    assert session is not None and session.owner_id == user.id

    empty = client.post(f"{URL}/{state['session_id']}/turns", json={}, headers=auth)
    assert empty.status_code == 422
    long = client.post(
        f"{URL}/{state['session_id']}/turns",
        json={"text": "a" * (constants.MAX_TEXT_CHARS + 1)},
        headers=auth,
    )
    assert long.status_code == 422

    monkeypatch.setattr(
        "app.modules.launch_agent.services.turns.hit", lambda **_: False
    )
    limited = client.post(
        f"{URL}/{state['session_id']}/turns",
        json={"text": "Yozgi chegirma"},
        headers=auth,
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == "launch_agent_daily_limit"

    session.turns = constants.MAX_TURNS
    db.commit()
    spent = client.post(
        f"{URL}/{state['session_id']}/turns", json={"text": "5"}, headers=auth
    )
    assert spent.status_code == 429

    other = sign_up(client, email="boshqa@example.com")
    assert client.get(f"{URL}/{state['session_id']}", headers=other).status_code == 404


# -- past the questions: pictures, the preparation, the press ----------------


def _at_media(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, str], dict[str, Any], list[dict]]:
    auth, user = _ready(client, db)
    _floor(db, user)
    asked = _model(monkeypatch, HeardOut(offer="IELTS kursi", goal="views", budget="5"))
    state = _open(client, auth)
    state = _turn(client, auth, state["session_id"], text="IELTS kursi, ko'rishsin, 5$")
    assert state["stage"] == "media"
    return auth, state, asked


def _launch_of(db: Session, state: dict[str, Any]) -> CampaignLaunch:
    db.expire_all()
    launch = db.get(CampaignLaunch, state["launch_id"])
    assert launch is not None
    return launch


def test_no_picture_no_preparation(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, queued: list
) -> None:
    auth, state, _asked = _at_media(client, db, monkeypatch)

    state = _turn(client, auth, state["session_id"], slot="media", value="done")

    assert state["stage"] == "media"
    assert state["lines"] == [
        "Avval kamida bitta post tanlang yoki rasm, video yuklang."
    ]
    assert _launch_of(db, state).status == "draft"
    assert not [name for name, _args in queued if name.endswith("build_draft_task")]


def test_pictures_start_the_preparation_and_the_summary_carries_the_press(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, queued: list
) -> None:
    auth, state, asked = _at_media(client, db, monkeypatch)
    monkeypatch.setattr(stages, "launch_variants", lambda *_, **__: [object()])
    session = state["session_id"]

    state = _turn(client, auth, session, slot="media", value="done")

    assert (state["stage"], state["wait"]) == ("preparing", True)
    assert state["ask"] is None
    assert state["lines"][-1].startswith("Reklama tayyorlanmoqda")
    assert [name for name, _args in queued if name.endswith("build_draft_task")]
    assert _launch_of(db, state).status == "building"

    # Words change nothing any more, and no model is asked.
    said = _turn(client, auth, session, text="byudjetni 10 qiling")
    assert said["stage"] == "preparing"
    assert said["lines"][0].startswith("Sozlamalar saqlangan.")
    assert len(asked) == 1

    # The worker wrote the proposal.
    launch = _launch_of(db, state)
    launch.status = "ready"
    launch.draft = {
        "audience": {
            "ai": {"age_min": 18, "age_max": 35, "genders": ["female"]},
            "chosen": None,
        },
        "interests": {
            "ai": [{"label": "Ingliz tili", "query": "English"}],
            "chosen": None,
        },
        "creative": {
            "ai": [
                {"primary_text": "IELTS 7+ ga tayyorlaymiz.", "headline": "IELTS kursi"}
            ],
            "chosen": None,
        },
    }
    db.commit()

    state = client.get(f"{URL}/{session}", headers=auth).json()

    assert (state["stage"], state["wait"]) == ("review", False)
    assert state["card"]["age_min"] == 18 and state["card"]["genders"] == ["Ayollar"]
    assert state["card"]["interests"] == ["Ingliz tili"]
    assert state["card"]["adverts"][0]["headline"] == "IELTS kursi"
    values = [(option["value"], option["opens"]) for option in state["ask"]["options"]]
    assert values == [("start", ""), ("", "review")]
    assert state["ask"]["options"][0]["recommended"] is True

    made: list[str] = []

    def create(db: Session, *, launch: CampaignLaunch, business: Business) -> None:
        made.append(str(launch.id))
        launch.status = "creating"
        db.commit()

    monkeypatch.setattr(stages.creation, "request_creation", create)

    state = _turn(client, auth, session, slot="launch", value="start")

    assert made == [state["launch_id"]]
    assert (state["stage"], state["wait"]) == ("creating", True)

    launch = _launch_of(db, state)
    launch.status = "created"
    db.commit()
    done = client.get(f"{URL}/{session}", headers=auth).json()
    assert done["stage"] == "done" and done["ask"] is None
    assert done["lines"][-1].startswith("Reklama yaratildi")


def test_the_press_that_spends_is_refused_until_the_summary(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, state, _asked = _at_media(client, db, monkeypatch)
    made: list[str] = []
    monkeypatch.setattr(
        stages.creation, "request_creation", lambda *_, **__: made.append("x")
    )

    state = _turn(client, auth, state["session_id"], slot="launch", value="start")

    assert made == []
    assert state["stage"] == "media"


def test_what_the_create_refuses_is_said_and_the_press_stays(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ads.exceptions import LaunchNotReady

    auth, state, _asked = _at_media(client, db, monkeypatch)
    launch = _launch_of(db, state)
    launch.status = "ready"
    db.commit()

    def refuse(*_: Any, **__: Any) -> None:
        raise LaunchNotReady

    monkeypatch.setattr(stages.creation, "request_creation", refuse)

    state = _turn(client, auth, state["session_id"], slot="launch", value="start")

    assert state["stage"] == "review"
    assert state["lines"] == ["Bu reklama hali tayyor emas."]
    assert state["ask"]["options"][0]["value"] == "start"


def test_a_preparation_that_failed_can_be_tried_again(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, queued: list
) -> None:
    auth, state, _asked = _at_media(client, db, monkeypatch)
    launch = _launch_of(db, state)
    launch.status = "failed"
    launch.error_message = "AI javob bermadi."
    db.commit()

    failed = client.get(f"{URL}/{state['session_id']}", headers=auth).json()
    assert failed["stage"] == "failed"
    assert failed["ask"]["text"] == "AI javob bermadi."
    assert [option["value"] for option in failed["ask"]["options"]] == ["retry"]


# -- what the advert sold is remembered, and offered next time ---------------


def test_what_was_advertised_waits_and_is_kept_once_the_advert_is_created(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    _floor(db, user)
    business = db.scalars(select(Business).where(Business.user_id == user.id)).one()
    _model(
        monkeypatch,
        HeardOut(
            offer="IELTS kursi, oyiga 600 000 so'm",
            goal="views",
            budget="5",
            sold_name="IELTS kursi",
            sold_price="oyiga 600 000 so'm",
        ),
    )
    state = _open(client, auth)

    state = _turn(client, auth, state["session_id"], text="IELTS kursi 600 ming, 5$")

    assert state["stage"] == "media"
    db.expire_all()
    view = known(db, business)
    # Said, not yet theirs: it waits on the business's list.
    assert view.active_items == []
    (waiting,) = view.pending
    assert waiting["src"] == "launch_agent"
    assert waiting["changes"] == [
        {"op": "add_item", "name": "IELTS kursi", "price": "oyiga 600 000 so'm"}
    ]

    # Saying more does not propose it twice.
    _turn(client, auth, state["session_id"], slot="budget", value="6")
    db.expire_all()
    assert len(known(db, business).pending) == 1

    launch = _launch_of(db, state)
    launch.status = "created"
    db.commit()
    done = client.get(f"{URL}/{state['session_id']}", headers=auth).json()

    assert done["stage"] == "done"
    db.expire_all()
    view = known(db, business)
    assert view.pending == []
    (item,) = view.active_items
    assert (item["name"], item["price"]) == ("IELTS kursi", "oyiga 600 000 so'm")
    assert db.get(LaunchAgentSession, state["session_id"]).status == "closed"  # type: ignore[union-attr]
    # Asked again, nothing is done twice.
    again = client.get(f"{URL}/{state['session_id']}", headers=auth).json()
    assert again["status"] == "closed"


def test_what_the_business_sells_is_offered_as_a_press_next_time(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.businesses.services import knowledge

    auth, user = _ready(client, db)
    _floor(db, user)
    business = db.scalars(select(Business).where(Business.user_id == user.id)).one()
    knowledge.apply(
        db,
        business=business,
        source="owner",
        changes=[
            {"op": "add_item", "name": "IELTS kursi", "price": "600 000 so'm"},
            {"op": "add_item", "name": "Rus tili"},
        ],
    )
    db.commit()
    asked = _model(monkeypatch)

    state = _open(client, auth)

    assert state["ask"]["slot"] == "offer"
    offered = {option["label"]: option["value"] for option in state["ask"]["options"]}
    assert offered == {
        "IELTS kursi": "IELTS kursi — 600 000 so'm",
        "Rus tili": "Rus tili",
    }

    state = _press(client, auth, state, "IELTS kursi — 600 000 so'm")

    assert state["ask"]["slot"] == "goal"
    assert state["chips"][-1]["value"] == "IELTS kursi — 600 000 so'm"
    assert asked == []  # a press costs no model call
    db.expire_all()
    # Already known: nothing new is proposed for it.
    assert known(db, business).pending == []


# -- a spoken message ---------------------------------------------------------


def _voice(
    client: TestClient,
    auth: dict[str, str],
    session: str,
    data: bytes = b"sound",
    **form: str,
) -> Any:
    return client.post(
        f"{URL}/{session}/voice",
        files={"file": ("gap.webm", data, "audio/webm")},
        data=form,
        headers=auth,
    )


def _scribe(
    monkeypatch: pytest.MonkeyPatch, text: str = "", *, error: Exception | None = None
) -> list[dict[str, Any]]:
    """Stand in for ElevenLabs; what it was asked is returned."""
    from speechkit import Transcript, Word

    from app.modules.launch_agent.services import voice

    asked: list[dict[str, Any]] = []

    class Fake:
        def __init__(self, **kwargs: Any) -> None:
            asked.append({"key": kwargs["api_key"]})

        def transcribe(self, **kwargs: Any) -> Transcript:
            asked[-1].update(kwargs, suffix=kwargs["path"].suffix)
            if error is not None:
                raise error
            words = tuple(Word(text=one, start=0, end=1) for one in text.split())
            return Transcript(language="uzb", text=text, words=words)

    monkeypatch.setattr(voice, "ElevenLabs", Fake)
    monkeypatch.setattr(voice.settings, "elevenlabs_voice_api_key", "voice-key")
    monkeypatch.setattr(voice.settings, "elevenlabs_api_key", "montage-key")
    monkeypatch.setattr(voice, "hit", lambda **_: True)
    return asked


def test_a_recording_comes_back_as_words_and_is_not_sent(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, _user = _ready(client, db)
    state = _open(client, auth)
    asked = _scribe(monkeypatch, "  Yozgi   chegirma, kuniga besh dollar ")

    answer = _voice(client, auth, state["session_id"], language="uz")

    assert answer.status_code == 200, answer.text
    assert answer.json() == {
        "text": "Yozgi chegirma, kuniga besh dollar",
        "language": "uzb",
    }
    # Its own key, never the montage's; the business's name goes as a key term.
    assert asked[0]["key"] == "voice-key"
    assert asked[0]["language"] == "uz"
    assert asked[0]["suffix"] == ".webm"
    assert asked[0]["keyterms"]
    # Nothing was said in the conversation on the person's behalf.
    after = client.get(f"{URL}/{state['session_id']}", headers=auth).json()
    assert after["messages"] == state["messages"]
    assert after["turns_left"] == state["turns_left"]


def test_a_recording_that_cannot_be_read_says_why(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from speechkit import SpeechAuthError, SpeechRejected, SpeechTemporaryError

    from app.modules.launch_agent.services import voice

    auth, _user = _ready(client, db)
    session = _open(client, auth)["session_id"]

    def code(**form: Any) -> tuple[int, str]:
        answer = _voice(client, auth, session, **form)
        return answer.status_code, answer.json()["code"]

    _scribe(monkeypatch, "")
    assert code() == (422, "launch_agent_voice_silent")
    assert code(data=b"") == (422, "launch_agent_voice_silent")
    limit = voice.VOICE_MAX_BYTES
    monkeypatch.setattr(voice, "VOICE_MAX_BYTES", 3)
    assert code() == (413, "launch_agent_voice_too_big")
    monkeypatch.setattr(voice, "VOICE_MAX_BYTES", limit)

    _scribe(monkeypatch, error=SpeechTemporaryError("busy"))
    assert code() == (503, "launch_agent_voice_busy")
    _scribe(monkeypatch, error=SpeechRejected("bad file"))
    assert code() == (422, "launch_agent_voice_refused")
    _scribe(monkeypatch, error=SpeechAuthError("bad key"))
    assert code() == (503, "launch_agent_voice_off")

    asked = _scribe(monkeypatch, "salom")
    monkeypatch.setattr(voice, "hit", lambda **_: False)
    assert code() == (429, "launch_agent_voice_daily_limit")
    # The montage's key alone does not turn the microphone on.
    monkeypatch.setattr(voice.settings, "elevenlabs_voice_api_key", "")
    assert code() == (503, "launch_agent_voice_off")
    assert asked == []

    other = sign_up(client, email="ovoz@example.com")
    assert _voice(client, other, session).status_code == 404
    client.post(f"{URL}/{session}/close", headers=auth)
    assert _voice(client, auth, session).status_code == 409
