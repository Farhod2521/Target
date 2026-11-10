"""The AI chat handing a question it could not answer to Support - the parts
that need no database: what Support reads, and a visitor's question kept
until they leave a phone."""

import uuid

from app.common.db import utcnow
from app.modules.chat.services.handoff import (
    ANSWER_CHARS,
    HEADER,
    HandoffState,
    forget,
    hand_over,
    handoff_in,
    handoff_item,
    handoff_text,
    waiting_for,
)
from app.modules.supportchat.constants import MAX_BODY_CHARS


def test_support_reads_the_question_and_what_the_assistant_said() -> None:
    text = handoff_text(question="To'lov o'tmadi", answer="Mutaxassisga  yubordim.\n")

    assert text.splitlines()[0] == HEADER
    assert "Savol: To'lov o'tmadi" in text
    assert "AI javobi: Mutaxassisga yubordim." in text


def test_a_long_answer_is_cut_and_the_whole_fits_one_support_message() -> None:
    text = handoff_text(question="q" * 1900, answer="a" * 5000)

    assert len(text) <= MAX_BODY_CHARS
    assert "a" * (ANSWER_CHARS + 1) not in text


def test_a_visitor_is_asked_for_a_phone_and_the_question_waits_once() -> None:
    turn_id = str(uuid.uuid4())
    state = hand_over(
        None,  # type: ignore[arg-type] - a visitor's turn never touches it
        turn_id=turn_id,
        owner=None,
        payload={"question": "Hisobim bloklandi", "owner_id": ""},
        answer="Mutaxassisga yuboraman.",
        now=utcnow(),
    )

    assert state == HandoffState.ASK_PHONE
    waiting = waiting_for(turn_id)
    assert waiting is not None and waiting.question == "Hisobim bloklandi"
    forget(turn_id)
    assert waiting_for(turn_id) is None


def test_an_empty_question_hands_nothing_over() -> None:
    state = hand_over(
        None,  # type: ignore[arg-type]
        turn_id="t",
        owner=None,
        payload={"question": "  "},
        answer="",
        now=utcnow(),
    )

    assert state == ""


def test_the_state_is_read_back_off_the_answers_row() -> None:
    stored = [{"kind": "reply", "label": "Ha"}, handoff_item(HandoffState.SENT)]

    assert handoff_in(stored) == "sent"
    assert handoff_in([]) == "" and handoff_in(None) == ""
