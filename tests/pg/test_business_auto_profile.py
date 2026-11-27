"""Nobody is asked to describe their business any more: its profile is
written from the page when the pair is made, its kind is guessed from what
the page says and kept as a guess, and the chat settles it with a button."""

from contextlib import contextmanager
from typing import Any

import pytest
from llmkit import LLMError, LLMResult, ToolCall
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.assistant.constants import Author, ButtonKind, ButtonState
from app.modules.assistant.models import AssistantMessage, AssistantSession
from app.modules.assistant.services import buttons
from app.modules.assistant.services.answer import Desk, _kind_buttons
from app.modules.assistant.services.knowledge import KIND_SAVED
from app.modules.audit.models import LLMCall
from app.modules.businesses.constants import KnowledgeSource, TypeState
from app.modules.businesses.models import Business, BusinessCategory, BusinessSubtype
from app.modules.businesses.selectors.knowledge import brief, known
from app.modules.businesses.services import guess, kinds
from app.modules.chat.selectors.context import _kind_lines
from app.modules.integrations.models import PageAccount
from core.assistant.prompt import sections_for
from core.assistant.tools import KIND_TOOL, BusinessKind
from core.business_kind import KindGuess
from core.chat.context import AccountDigest, BusinessDigest, ChatContext, TotalsDigest
from core.chat.verify import FigureGate
from tests.pg.test_business_links import World

TASK = "app.modules.businesses.tasks.guess_business_kind_task"


def _directions(db: Session) -> dict[str, BusinessCategory]:
    rows = {
        key: BusinessCategory(key=key, label_uz=label, preset_key=key, position=place)
        for place, (key, label) in enumerate(
            (("education", "Ta'lim"), ("ecommerce", "Savdo"), ("services", "Xizmatlar"))
        )
    }
    db.add_all(rows.values())
    db.flush()
    return rows


def _paired(db: Session, **page_says: str) -> tuple[World, PageAccount, Business]:
    """An owner whose page was paired with nobody describing the business."""
    world = World(db)
    page = world.page("p1", profile=False)
    page.name = page_says.pop("name", "Zukko Academy | Toshkent")
    for field, value in page_says.items():
        setattr(page, field, value)
    page.is_current = True
    world.pair(page, world.account("act_1"))
    world.sync()
    db.commit()
    business = db.scalars(select(Business).where(Business.page_id == page.id)).one()
    return world, page, business


def _model(answer: KindGuess | Exception, asked: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
    class Fake:
        def structured(self, **ask: Any) -> LLMResult[KindGuess]:
            asked.append(ask)
            if isinstance(answer, Exception):
                raise answer
            return LLMResult(
                value=answer,
                input_tokens=300,
                output_tokens=40,
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

    return factory


# -- the profile nobody filled in --------------------------------------------


def test_a_paired_page_gets_its_profile_and_a_guess_is_queued(
    db: Session, queued: list
) -> None:
    _world, _page, business = _paired(db, location_city="Toshkent")

    assert business.name == "Zukko Academy | Toshkent"
    assert business.city == "Toshkent"
    assert business.category and business.direction_id is None
    assert (TASK, (str(business.id),)) in queued
    view = known(db, business)
    assert view.type_state == TypeState.UNSET
    # The placeholder is not said as the business's kind.
    assert view.type_label == ""
    assert "Kind:" not in brief(db, business)


def test_a_profile_written_by_hand_is_left_alone(db: Session, queued: list) -> None:
    world = World(db)
    page = world.page("p1")  # described by its owner
    world.pair(page, world.account("act_1"))
    world.sync()
    db.commit()

    assert len(db.scalars(select(Business)).all()) == 1
    assert not [name for name, _args in queued if name == TASK]


# -- the guess ---------------------------------------------------------------


def test_a_guess_is_kept_as_a_guess(db: Session) -> None:
    rows = _directions(db)
    _world, page, business = _paired(
        db, instagram_biography="Ingliz tili kurslari. IELTS 7+"
    )

    done = guess.keep(
        db,
        business=business,
        page=page,
        guess=KindGuess(
            direction="education",
            subtype="ingliz tili kurslari",
            name="Zukko Academy",
            about="Ingliz tili va IELTS kurslari o'tadi.",
        ),
    )
    db.commit()

    assert (done.direction, done.subtype) == ("education", "ingliz tili kurslari")
    assert done.renamed and done.proposed_about
    view = known(db, business)
    assert view.type_state == TypeState.GUESSED
    assert view.direction is not None and view.direction.id == rows["education"].id
    assert view.subtype is not None and view.subtype.name == "ingliz tili kurslari"
    assert business.name == "Zukko Academy"
    assert business.category == "education"
    # What the business does is not written down until somebody says yes.
    assert view.about is None
    assert view.pending[0]["src"] == KnowledgeSource.PAGE
    assert "(our guess, not confirmed by the business)" in brief(db, business)


def test_a_name_that_is_not_on_the_page_is_not_taken(db: Session) -> None:
    _directions(db)
    _world, page, business = _paired(db)

    done = guess.keep(
        db,
        business=business,
        page=page,
        guess=KindGuess(direction="education", name="Oxford School"),
    )

    assert not done.renamed
    assert business.name == "Zukko Academy | Toshkent"


def test_a_kind_off_the_list_is_no_kind(db: Session) -> None:
    _directions(db)
    _world, page, business = _paired(db)

    done = guess.keep(
        db, business=business, page=page, guess=KindGuess(direction="spaceflight")
    )

    assert done.direction == ""
    assert known(db, business).type_state == TypeState.UNSET


def test_a_guess_never_overwrites_what_somebody_said(db: Session) -> None:
    rows = _directions(db)
    _world, page, business = _paired(db)
    kinds.set_kind(db, business=business, direction=rows["ecommerce"])
    db.commit()

    done = guess.keep(
        db, business=business, page=page, guess=KindGuess(direction="education")
    )

    assert done.direction == ""
    assert known(db, business).direction.id == rows["ecommerce"].id  # type: ignore[union-attr]
    assert known(db, business).type_state == TypeState.CONFIRMED


def test_the_worker_asks_once_and_writes_what_it_cost(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _directions(db)
    _world, _page, business = _paired(
        db, instagram_biography="Ingliz tili kurslari", instagram_username="zukko.uz"
    )
    asked: list[dict[str, Any]] = []
    monkeypatch.setattr(
        guess, "claude", _model(KindGuess(direction="education"), asked)
    )

    done = guess.guess_kind(db, business_id=str(business.id))
    db.commit()

    assert done is not None and done.direction == "education"
    (ask,) = asked
    assert "Instagram bio: Ingliz tili kurslari" in ask["system"]
    assert "- education - Ta'lim" in ask["system"]
    assert "{{" not in ask["system"]
    call = db.scalars(select(LLMCall)).one()
    assert call.prompt_name == "business_kind"

    # Guessed already: the worker does not ask again.
    assert guess.guess_kind(db, business_id=str(business.id)) is None
    assert len(asked) == 1


def test_a_model_that_cannot_be_reached_leaves_the_kind_unset(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _directions(db)
    _world, _page, business = _paired(db)
    monkeypatch.setattr(guess, "claude", _model(LLMError("down"), []))

    assert guess.guess_kind(db, business_id=str(business.id)) is None
    assert known(db, business).type_state == TypeState.UNSET


# -- what the chat is told ---------------------------------------------------


def test_the_chat_is_told_how_sure_the_kind_is(db: Session) -> None:
    rows = _directions(db)
    _world, page, business = _paired(db)

    unknown = _kind_lines(db, known(db, business))
    assert unknown["kind_note"].startswith("not known yet")
    assert "education - Ta'lim" in unknown["kind_choices"]

    guess.keep(
        db,
        business=business,
        page=page,
        guess=KindGuess(direction="education", subtype="ingliz tili kurslari"),
    )
    guessed = _kind_lines(db, known(db, business))
    assert guessed["kind_note"].startswith("Ta'lim → ingliz tili kurslari - our guess")

    kinds.set_kind(db, business=business, direction=rows["education"])
    assert _kind_lines(db, known(db, business)) == {}


def test_the_rules_for_settling_the_kind_travel_with_the_line() -> None:
    def drawn(**kind: str) -> str:
        return ChatContext(
            account=AccountDigest(
                business=BusinessDigest(
                    name="B", category="not known yet", offer="", currency="USD", **kind
                ),
                totals=TotalsDigest(window_days=7, spend="$0"),
                maturity="",
            )
        ).render()

    asking = drawn(kind_note="not known yet", kind_choices="education - Ta'lim")
    settled = drawn()

    assert "- Kind: not known yet" in asking
    assert "- Kinds to choose from: education - Ta'lim" in asking
    assert "kind" in sections_for(context=asking, question="Salom")
    assert "Kind" not in settled
    assert "kind" not in sections_for(context=settled, question="Salom")


# -- the chat settles it -----------------------------------------------------


def _desk(db: Session, world: World) -> Desk:
    return Desk(
        db=db,
        owner=world.owner,
        now=utcnow(),
        gate=FigureGate(allowed=frozenset()),
        language="uz",
        shown_in="uz",
    )


def _kind(desk: Desk, **said: str) -> str:
    out = desk(ToolCall(id="k", name=KIND_TOOL, arguments=BusinessKind(**said)))
    return str(out.text)


def _answer(db: Session, world: World, desk: Desk) -> AssistantMessage:
    thread = AssistantSession(owner_id=world.owner.id, title="Savol")
    db.add(thread)
    db.flush()
    row = AssistantMessage(
        owner_id=world.owner.id,
        session_id=thread.id,
        author=Author.AI,
        buttons=_kind_buttons(payload={"shown": "uz"}, desk=desk),
    )
    db.add(row)
    db.commit()
    return row


def test_the_kind_is_prepared_and_theirs_only_when_pressed(db: Session) -> None:
    rows = _directions(db)
    world, _page, business = _paired(db)
    desk = _desk(db, world)

    told = _kind(
        desk, direction="education", subtype="Ingliz tili kurslari", name="Zukko"
    )

    assert told.startswith("Prepared, and nothing is saved yet.")
    assert "- Biznes turi: Ta'lim → Ingliz tili kurslari" in told
    assert "- Nomi: Zukko" in told
    assert desk.made == 0
    assert known(db, business).type_state == TypeState.UNSET

    row = _answer(db, world, desk)
    (button,) = row.buttons
    assert button["kind"] == ButtonKind.BUSINESS_KIND
    assert (button["key"], button["label"]) == ("B1", "Tasdiqlash")
    assert button["lines"] == [
        "Biznes turi: Ta'lim → Ingliz tili kurslari",
        "Nomi: Zukko",
    ]
    assert db.scalar(select(BusinessSubtype.id)) is None  # nothing made yet

    pressed = buttons.press(
        db, owner=world.owner, message_id=str(row.id), key="B1", now=utcnow()
    )
    db.commit()

    assert (pressed.state, pressed.text) == (ButtonState.DONE, KIND_SAVED)
    view = known(db, business)
    assert view.type_state == TypeState.CONFIRMED
    assert view.direction is not None and view.direction.id == rows["education"].id
    assert view.subtype is not None and view.subtype.name == "Ingliz tili kurslari"
    assert view.profile.name == "Zukko"
    assert view.profile.category == "education"


def test_a_key_that_is_not_a_kind_is_refused(db: Session) -> None:
    _directions(db)
    world, _page, _business = _paired(db)
    desk = _desk(db, world)

    told = _kind(desk, direction="spaceflight")

    assert told.startswith("Not prepared: 'spaceflight' is not a kind's key.")
    assert desk.kinds == []


def test_a_kind_already_confirmed_is_not_asked_again(db: Session) -> None:
    rows = _directions(db)
    world, _page, business = _paired(db)
    kinds.set_kind(db, business=business, direction=rows["education"])
    db.commit()
    desk = _desk(db, world)

    assert _kind(desk, direction="education").startswith("Nothing to confirm")
    # Another kind is a change, and is prepared.
    assert _kind(desk, direction="ecommerce").startswith("Prepared")


def test_a_no_leaves_the_kind_as_it_was(db: Session) -> None:
    _directions(db)
    world, _page, business = _paired(db)
    desk = _desk(db, world)
    _kind(desk, direction="education")
    row = _answer(db, world, desk)

    said = buttons.dismiss(
        db, owner=world.owner, message_id=str(row.id), key="B1", now=utcnow()
    )
    db.commit()

    assert said.state == ButtonState.DISMISSED
    assert known(db, business).type_state == TypeState.UNSET
