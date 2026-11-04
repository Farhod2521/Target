"""A name, a phone or an email the owner wants typed rather than prefilled.

Ported from Django's tests/apps/ads/test_typed_contacts.py (c650b52e, 401f4304).
The screens take the question, the launch sends it as written, a form already
on the page that asks one is offered like any other, and an AI form asks the
name and the telephone this way too, each under a key the lead is read by.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from metaads.leadforms import questions_for

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import NEW_ROW_PREFIX, DraftSection
from app.modules.ads.inputs.ending import EndingIn
from app.modules.ads.inputs.lead_form import LeadFormPickIn, check_pick
from app.modules.ads.inputs.questions import (
    QuestionRow,
    TypedQuestion,
    read_rows,
    rows_error,
)
from app.modules.ads.services.meta_specs import _questions
from app.modules.leads.selectors.reads import custom_questions
from core.leads import normalise

TYPED_FORM: list[dict[str, Any]] = [
    {
        "type": "CUSTOM",
        "label": "Siz Toshkent shahrida yashaysizmi?",
        "options": [{"key": "ha", "value": "Ha"}, {"key": "yoq", "value": "Yo'q"}],
    },
    {"type": "CUSTOM", "label": "Ismingiz"},
    {"type": "CUSTOM", "label": "Telefon raqamingiz"},
    {"type": "PHONE", "label": "Phone number"},
]


def _launch(questions: list[dict[str, Any]], **answers: Any) -> Any:
    draft = draft_field.empty_draft()
    draft_field.choose(draft, DraftSection.FORM, questions)
    return SimpleNamespace(draft=draft, answers=answers)


def test_the_builder_takes_a_typed_name_question() -> None:
    _id, questions, _name, _ending = check_pick(
        LeadFormPickIn(
            kinds=["phone"],
            typed=[TypedQuestion(label="Ism familiyangiz")],
            ending=EndingIn(kind="none"),
        ),
        default_name="Moto bikes · Test-drayv",
        taken_names=frozenset(),
        region="UZ",
        default_title="Rahmat",
    )

    assert questions is not None
    assert "Ism familiyangiz" in [item["label"] for item in questions]


def test_the_proposal_screen_takes_a_typed_name() -> None:
    edit = read_rows(
        [
            QuestionRow(key=f"{NEW_ROW_PREFIX}0", label="Qaysi kurs?"),
            QuestionRow(key=f"{NEW_ROW_PREFIX}1", label="Ismingiz"),
        ],
        offered=set(),
    )

    assert edit.added == ["Qaysi kurs?", "Ismingiz"]
    assert rows_error(edit) == ""


def test_the_model_asks_a_first_name_alone_as_one() -> None:
    kept = draft_field.model_questions(
        [{"kind": "first_name", "label": "Ism"}, {"kind": "phone", "label": "Tel"}],
        limit=3,
    )

    assert [item["label"] for item in kept] == ["Ismingiz", "Telefon raqamingiz"]


def test_the_models_name_parts_become_one_question() -> None:
    kept = draft_field.model_questions(
        [
            {"kind": "first_name", "label": "Ism"},
            {"kind": "last_name", "label": "Familiya"},
            {"kind": "phone", "label": "Tel"},
        ],
        limit=3,
    )

    assert [item["label"] for item in kept] == [
        "Ism familiyangiz",
        "Telefon raqamingiz",
    ]


def test_the_models_typed_contact_becomes_the_standard_question() -> None:
    questions = [
        {"kind": "custom", "label": "Ismingiz", "options": []},
        {"kind": "custom", "label": "Qaysi kurs?", "options": ["IELTS", "CEFR"]},
        {"kind": "phone", "label": "Telefon"},
        {"kind": "custom", "label": "Telefon raqamingiz", "options": []},
    ]

    kinds = [item["kind"] for item in draft_field.standard_contacts(questions)]

    assert kinds == ["full_name", "custom", "phone"]


def test_meta_is_sent_the_typed_questions_as_written() -> None:
    """A typed number counts as the telephone: no second one is added."""
    sent = _questions(
        _launch(
            [
                {"kind": "custom:1", "label": "Ism familiyangiz", "options": []},
                {"kind": "custom:2", "label": "Telefon raqamingiz", "options": []},
            ]
        )
    )

    assert [(q.kind, q.label) for q in sent] == [
        ("CUSTOM", "Ism familiyangiz"),
        ("CUSTOM", "Telefon raqamingiz"),
    ]


def test_an_ai_form_reaches_meta_under_the_keys_a_lead_is_read_by() -> None:
    questions = draft_field.model_questions(
        [
            {"kind": "full_name", "label": "Ismingiz"},
            {"kind": "phone", "label": "Telefon"},
            {"kind": "custom", "label": "Qaysi kurs?", "options": ["IELTS"]},
        ],
        limit=3,
    )

    sent = questions_for(_questions(_launch(questions)))

    assert [(row["type"], row["key"], row["label"]) for row in sent] == [
        ("CUSTOM", "typed_full_name", "Ism familiyangiz"),
        ("CUSTOM", "typed_phone", "Telefon raqamingiz"),
        ("CUSTOM", "q3", "Qaysi kurs?"),
    ]


def test_a_second_typed_phone_keeps_a_positional_key() -> None:
    sent = questions_for(
        _questions(
            _launch(
                [
                    {"kind": "custom:1", "label": "Telefon raqamingiz", "options": []},
                    {"kind": "custom:2", "label": "Qo'shimcha telefon", "options": []},
                ]
            )
        )
    )

    assert [row["key"] for row in sent] == ["typed_phone", "q2"]


def test_a_typed_name_alone_still_gets_a_telephone() -> None:
    sent = _questions(
        _launch([{"kind": "custom:1", "label": "Ism familiyangiz", "options": []}])
    )

    assert [q.kind for q in sent] == ["CUSTOM", "PHONE"]


def test_a_lead_from_a_typed_form_fills_its_name_and_phone() -> None:
    lead = normalise(
        field_data=[
            {"name": "typed_full_name", "values": ["Aziz Karimov"]},
            {"name": "typed_phone", "values": ["90 123 45 67"]},
            {"name": "q3", "values": ["IELTS"]},
        ],
        region="UZ",
    )

    assert lead.full_name == "Aziz Karimov"
    assert lead.phone_e164.endswith("901234567")
    assert lead.answers["q3"] == ("IELTS",)


def test_a_copy_carries_the_typed_questions() -> None:
    labels = [item["label"] for item in custom_questions(TYPED_FORM)]

    assert labels == [
        "Siz Toshkent shahrida yashaysizmi?",
        "Ismingiz",
        "Telefon raqamingiz",
    ]


@pytest.mark.parametrize("raw", [None, [], [{"type": "FULL_NAME"}, {"type": "PHONE"}]])
def test_a_form_without_typed_questions_copies_nothing(raw: Any) -> None:
    assert custom_questions(raw) == ()


@pytest.mark.parametrize(
    "questions",
    [
        [{"kind": "full_name", "label": "Ism"}, {"kind": "phone", "label": "Tel"}],
        [{"kind": "custom:1", "label": "Qaysi kurs?"}],
        [
            {"kind": "custom:1", "label": "Telefon raqamingiz", "options": ["A", "B"]},
            {"kind": "email", "label": "Email"},
        ],
    ],
)
def test_a_quality_form_never_has_meta_fill_the_name_or_the_phone(
    questions: list[dict[str, Any]],
) -> None:
    sent = questions_for(_questions(_launch(questions, higher_intent=True)))

    kinds = [row["type"] for row in sent]
    assert "PHONE" not in kinds
    assert "FULL_NAME" not in kinds
    assert "Telefon raqamingiz" in [row.get("label") for row in sent]


def test_a_short_form_keeps_meta_filling_the_phone_its_owner_ticked() -> None:
    sent = questions_for(
        _questions(_launch([{"kind": "phone", "label": "Tel"}], higher_intent=False))
    )

    assert [row["type"] for row in sent] == ["PHONE"]


def test_the_picker_counts_only_the_owners_own_questions() -> None:
    _id, questions, _name, _ending = check_pick(
        LeadFormPickIn(
            kinds=["full_name", "phone", "email", "city"],
            typed=[TypedQuestion(label=f"{index}-savol") for index in range(12)],
            ending=EndingIn(kind="none"),
        ),
        default_name="Forma",
        taken_names=frozenset(),
        region="UZ",
        default_title="Rahmat",
    )

    assert questions is not None
    assert len(questions) == 16
