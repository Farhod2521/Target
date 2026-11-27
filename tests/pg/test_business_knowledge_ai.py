"""What is known about a business reaching every model that speaks of it,
and the cabinet's chat keeping what a person says about their business:
prepared by the model, kept only when its button is pressed."""

from types import SimpleNamespace
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from llmkit import PromptLibrary, ToolCall
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.selectors.copy_notes import AdvertFacts
from app.modules.agent.services.describe_account import account_block
from app.modules.assistant.constants import Author, ButtonKind, ButtonState
from app.modules.assistant.models import AssistantMessage, AssistantSession
from app.modules.assistant.services import buttons
from app.modules.assistant.services.answer import Desk, _kept_notes
from app.modules.assistant.services.knowledge import SAVED_WORDS
from app.modules.businesses.constants import FactKey, ItemKind, KnowledgeSource
from app.modules.businesses.models import Business
from app.modules.businesses.selectors.knowledge import (
    NOTHING_KNOWN,
    known,
    learned,
    learned_text,
    waiting_lines,
)
from app.modules.businesses.services import knowledge
from core.agent import PROMPT_DIR
from core.agent.copy_check import AdWords, check_against_offer
from core.assistant.tools import (
    NOTE_TOOL,
    TOOLS,
    BusinessNote,
    FactName,
    FactNote,
    SoldNote,
)
from core.chat.context import AccountDigest, BusinessDigest, ChatContext, TotalsDigest
from core.chat.verify import FigureGate
from tests.pg.test_assistant import URL, _ask, _Script, _thread, _with_plan
from tests.pg.test_business_links import World
from tests.pg.test_business_members import _business


def _shop(db: Session) -> tuple[World, Business]:
    """An owner on their page, whose business sells two things."""
    world = World(db)
    business = _business(world)
    page = world.db.get(type(world.page("p9", profile=False)), business.page_id)
    assert page is not None
    page.is_current = True
    knowledge.apply(
        db,
        business=business,
        source=KnowledgeSource.OWNER,
        changes=[
            {"op": "set_about", "text": "Maishiy texnika do'koni"},
            {"op": "add_item", "name": "Changyutgich", "price": "2 450 000 so'm"},
            {"op": "set_fact", "key": "delivery", "value": "Toshkent bo'ylab bepul"},
        ],
    )
    db.commit()
    return world, business


def _desk(db: Session, world: World) -> Desk:
    return Desk(
        db=db,
        owner=world.owner,
        now=utcnow(),
        gate=FigureGate(allowed=frozenset()),
        language="uz",
        shown_in="uz",
    )


def _note(desk: Desk, **said: object) -> str:
    out = desk(ToolCall(id="n", name=NOTE_TOOL, arguments=BusinessNote(**said)))
    return str(out.text)


def _answer(db: Session, world: World, desk: Desk) -> AssistantMessage:
    """The answer's row, with the buttons the finished answer would carry."""
    thread = AssistantSession(owner_id=world.owner.id, title="Savol")
    db.add(thread)
    db.flush()
    row = AssistantMessage(
        owner_id=world.owner.id,
        session_id=thread.id,
        author=Author.AI,
        text="Javob",
        buttons=_kept_notes(db, payload={"shown": "uz"}, desk=desk, now=utcnow()),
    )
    db.add(row)
    db.commit()
    return row


# -- what a prompt is given --------------------------------------------------


def test_nothing_known_is_an_empty_reading(db: Session) -> None:
    business = _business(World(db))

    assert learned(db, business) == ""


def test_what_was_learned_is_given_without_the_profile(db: Session) -> None:
    _world, business = _shop(db)

    text = learned(db, business)

    assert text.splitlines() == [
        "- What it does: Maishiy texnika do'koni",
        "- Products and services:",
        "  - Changyutgich — 2 450 000 so'm",
        "- Facts:",
        "  - Delivery: Toshkent bo'ylab bepul",
    ]
    assert business.name not in text
    assert len(learned(db, business, limit=60)) <= 60


def test_a_proposal_nobody_answered_is_read_as_waiting(db: Session) -> None:
    world, business = _shop(db)
    knowledge.propose(
        db,
        business=business,
        source=KnowledgeSource.ASSISTANT,
        actor=world.owner,
        changes=[{"op": "add_item", "name": "Dazmol", "price": "390 000 so'm"}],
    )

    view = known(db, business)

    assert waiting_lines(view) == ["Yangi taklif: Dazmol — 390 000 so'm"]
    assert "Dazmol" not in learned_text(view)


def test_the_chat_is_told_what_is_kept_and_what_waits() -> None:
    context = ChatContext(
        account=AccountDigest(
            business=BusinessDigest(
                name="Biznes",
                category="Savdo",
                offer="Texnika",
                currency="USD",
                known=("- Products and services:", "  - Changyutgich — 2 450 000 so'm"),
                waiting=("Yangi taklif: Dazmol",),
            ),
            totals=TotalsDigest(window_days=7, spend="$0"),
            maturity="",
        )
    )

    drawn = context.render()

    assert "- Kept about the business, said by its own people:" in drawn
    assert "    - Changyutgich — 2 450 000 so'm" in drawn
    assert "- Proposed to be kept, waiting for the owner's yes:" in drawn
    assert "  - Yangi taklif: Dazmol" in drawn
    # A price the business gave may be said back by the chat.
    assert "2450000" in context.figures()


def test_a_business_nothing_is_kept_of_reads_as_before() -> None:
    context = ChatContext(
        account=AccountDigest(
            business=BusinessDigest(
                name="Biznes", category="Savdo", offer="Texnika", currency="USD"
            ),
            totals=TotalsDigest(window_days=7, spend="$0"),
            maturity="",
        )
    )

    assert "Kept about" not in context.render()
    assert "Proposed to be kept" not in context.render()


def test_the_nightly_review_reads_what_is_kept(db: Session) -> None:
    _world, business = _shop(db)
    # As much of the account's facts as the block reads.
    account: Any = SimpleNamespace(
        currency="USD",
        window_days=7,
        totals=SimpleNamespace(spend_minor=0),
        usual={},
        adsets=(),
    )

    block = account_block(
        account=account,
        business=business,
        language="uz",
        known=learned(db, business),
    )
    plain = account_block(account=account, business=business, language="uz")

    assert "  - Changyutgich — 2 450 000 so'm" in block
    assert "Changyutgich" not in plain


def test_a_price_from_what_is_kept_is_not_an_invented_one() -> None:
    words = AdWords(
        primary_text="Changyutgich 2 450 000 so'm. Ariza qoldiring.",
        headline="Changyutgich",
        description="",
    )
    bare = AdvertFacts(offer="Maishiy texnika")
    told = AdvertFacts(
        offer="Maishiy texnika", known="  - Changyutgich — 2 450 000 so'm"
    )

    assert "number_not_in_offer" in {
        found.code
        for found in check_against_offer(
            words=words, facts=bare.joined, sends_to="form"
        )
    }
    assert "number_not_in_offer" not in {
        found.code
        for found in check_against_offer(
            words=words, facts=told.joined, sends_to="form"
        )
    }


def test_the_prompts_that_write_adverts_have_a_place_for_it() -> None:
    library = PromptLibrary(root=PROMPT_DIR)

    for name in ("launch_draft", "ad_refresh"):
        text, _version = library.get(name)
        assert "{{ business_knowledge }}" in text, name
    assert NOTHING_KNOWN.startswith("- ")


def test_the_tool_and_the_business_spell_their_lists_alike() -> None:
    assert set(get_args(FactName)) == {key.value for key in FactKey}
    kinds = set(get_args(SoldNote.model_fields["kind"].annotation))
    assert kinds == {kind.value for kind in ItemKind}
    assert NOTE_TOOL in {tool.name for tool in TOOLS}


# -- the chat keeps what a person says ---------------------------------------


def test_what_a_person_says_is_prepared_and_kept_only_when_pressed(
    db: Session,
) -> None:
    world, business = _shop(db)
    desk = _desk(db, world)

    told = _note(
        desk,
        items=[
            SoldNote(name="Dazmol", kind="product", price="390 000 so'm"),
            SoldNote(name="changyutgich", price="2 300 000 so'm"),
        ],
        facts=[FactNote(key="guarantee", value="1 yil kafolat")],
    )

    assert told.startswith("Prepared, and nothing is saved yet.")
    assert "- Yangi taklif: Dazmol — 390 000 so'm" in told
    assert desk.made == 0  # a note costs no look-up
    assert "Dazmol" not in learned(db, business)

    row = _answer(db, world, desk)
    (button,) = row.buttons
    assert button["kind"] == ButtonKind.KNOWLEDGE
    assert button["key"] == "K1"
    assert button["state"] == ButtonState.OPEN
    assert button["label"] == "Eslab qolish"
    assert len(button["lines"]) == 3
    assert len(known(db, business).pending) == 1
    assert "Dazmol" not in learned(db, business)

    pressed = buttons.press(
        db, owner=world.owner, message_id=str(row.id), key="K1", now=utcnow()
    )
    db.commit()

    assert (pressed.state, pressed.text) == (ButtonState.DONE, SAVED_WORDS)
    view = known(db, business)
    assert view.pending == []
    held = {str(item["name"]): item for item in view.items}
    assert held["Dazmol"]["price"] == "390 000 so'm"
    assert held["Dazmol"]["src"] == KnowledgeSource.ASSISTANT
    # The thing already kept is changed, under the name it was kept by.
    assert held["Changyutgich"]["price"] == "2 300 000 so'm"
    assert view.facts["guarantee"]["value"] == "1 yil kafolat"

    again = buttons.press(
        db, owner=world.owner, message_id=str(row.id), key="K1", now=utcnow()
    )
    assert (again.state, again.text) == (ButtonState.DONE, SAVED_WORDS)


def test_what_is_already_kept_is_not_proposed_again(db: Session) -> None:
    world, _business_row = _shop(db)
    desk = _desk(db, world)

    told = _note(
        desk,
        about="Maishiy texnika do'koni",
        items=[SoldNote(name="CHANGYUTGICH", price="2 450 000 so'm")],
        facts=[FactNote(key="delivery", value="Toshkent bo'ylab bepul")],
    )

    assert told.startswith("Nothing new to keep")
    assert desk.notes == []


def test_one_note_an_answer(db: Session) -> None:
    world, _business_row = _shop(db)
    desk = _desk(db, world)

    _note(desk, items=[SoldNote(name="Dazmol")])
    second = _note(desk, items=[SoldNote(name="Muzlatgich")])

    assert second == "A note is already prepared for this answer."
    assert len(desk.notes) == 1


def test_a_thing_no_longer_sold_leaves_the_list_when_pressed(db: Session) -> None:
    world, business = _shop(db)
    desk = _desk(db, world)

    told = _note(
        desk,
        items=[
            SoldNote(name="Changyutgich", gone=True),
            SoldNote(name="Hech qachon bo'lmagan", gone=True),
        ],
    )
    assert "- Endi sotilmaydi: Changyutgich" in told

    row = _answer(db, world, desk)
    buttons.press(db, owner=world.owner, message_id=str(row.id), key="K1", now=utcnow())
    db.commit()

    assert known(db, business).active_items == []
    assert len(known(db, business).items) == 1


def test_a_no_takes_the_note_off_the_waiting_list(db: Session) -> None:
    world, business = _shop(db)
    desk = _desk(db, world)
    _note(desk, items=[SoldNote(name="Dazmol")])
    row = _answer(db, world, desk)

    said = buttons.dismiss(
        db, owner=world.owner, message_id=str(row.id), key="K1", now=utcnow()
    )
    db.commit()

    assert said.state == ButtonState.DISMISSED
    assert known(db, business).pending == []
    assert "Dazmol" not in learned(db, business)


def test_a_note_answered_elsewhere_is_gone_here(db: Session) -> None:
    world, business = _shop(db)
    desk = _desk(db, world)
    _note(desk, items=[SoldNote(name="Dazmol")])
    row = _answer(db, world, desk)
    (waiting,) = known(db, business).pending
    knowledge.reject(db, business=business, proposal_id=waiting["id"])
    db.commit()

    pressed = buttons.press(
        db, owner=world.owner, message_id=str(row.id), key="K1", now=utcnow()
    )
    db.commit()

    assert pressed.state == ButtonState.GONE
    assert "Dazmol" not in learned(db, business)


def test_another_owners_business_is_never_written(db: Session) -> None:
    world, business = _shop(db)
    desk = _desk(db, world)
    _note(desk, items=[SoldNote(name="Dazmol")])
    row = _answer(db, world, desk)
    stranger = World(db, email="begona@example.com")
    foreign = AssistantMessage(
        owner_id=stranger.owner.id,
        session_id=_thread_of(db, stranger),
        author=Author.AI,
        buttons=[dict(row.buttons[0])],
    )
    db.add(foreign)
    db.commit()

    pressed = buttons.press(
        db, owner=stranger.owner, message_id=str(foreign.id), key="K1", now=utcnow()
    )
    db.commit()

    assert pressed.state == ButtonState.GONE
    assert len(known(db, business).pending) == 1
    assert "Dazmol" not in learned(db, business)


def _thread_of(db: Session, world: World):  # type: ignore[no-untyped-def]
    thread = AssistantSession(owner_id=world.owner.id, title="Savol")
    db.add(thread)
    db.flush()
    return thread.id


def test_a_person_with_no_business_is_answered_as_usual(db: Session) -> None:
    world = World(db)
    desk = _desk(db, world)

    told = _note(desk, items=[SoldNote(name="Dazmol")])

    assert told.startswith("Not kept: this account has no business")
    assert desk.notes == []


# -- the whole way, through the chat's own door ------------------------------


def test_the_chat_keeps_what_it_was_told_from_question_to_button(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner = _with_plan(client, db)
    business = Business(
        user_id=owner.id, name="Texno", timezone="Asia/Tashkent", category="ecommerce"
    )
    db.add(business)
    db.flush()
    knowledge.apply(
        db,
        business=business,
        source=KnowledgeSource.OWNER,
        changes=[{"op": "add_item", "name": "Changyutgich", "price": "2 450 000 so'm"}],
    )
    db.commit()
    script = _Script(
        calls=[
            (
                NOTE_TOOL,
                BusinessNote(items=[SoldNote(name="Dazmol", price="390 000 so'm")]),
            )
        ],
        words=["Tushunarli. ", "Buni eslab qolishim mumkin."],
    )

    turn = _ask(
        client,
        db,
        headers,
        monkeypatch,
        script,
        question="Bizda dazmol ham bor, 390 000 so'm",
    )

    # The model was told what is already kept, and was offered the tool.
    (asked,) = script.asked
    assert "  - Changyutgich — 2 450 000 so'm" in asked["system_tail"]
    assert NOTE_TOOL in {tool.name for tool in asked["tools"]}
    assert script.seen[0].startswith("Prepared, and nothing is saved yet.")

    thread = _thread(client, headers, turn["session_id"])
    answer = thread["messages"][1]
    (button,) = answer["buttons"]
    assert button["kind"] == "knowledge"
    assert button["state"] == "open"
    assert button["lines"] == ["Yangi taklif: Dazmol — 390 000 so'm"]
    assert "Dazmol" not in learned(db, business)

    pressed = client.post(
        f"{URL}/buttons/{answer['id']}/{button['key']}", headers=headers
    )
    assert pressed.status_code == 200, pressed.text
    assert pressed.json()["state"] == "done"
    assert pressed.json()["text"] == SAVED_WORDS
    db.expire_all()
    assert "  - Dazmol — 390 000 so'm" in learned(db, business)

    again = _thread(client, headers, turn["session_id"])["messages"][1]["buttons"][0]
    assert (again["state"], again["state_text"]) == ("done", SAVED_WORDS)
