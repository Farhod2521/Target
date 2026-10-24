"""Every answer, in a shape that can be asked about - and put back beside
the question that produced it.

Two functions and one problem between them. A lead's answer sheet arrives
as a list keyed by field name, which is a shape a database cannot be asked
"what did people answer to q2" about; and the question that produced ``q2``
lives on the form rather than on the lead, so a screen reading the sheet
alone shows a column of keys.

No Django here, which is the point: both halves are decided in ``core`` and
checked without a form, a lead or a database.
"""

import pytest

from core.leads import label_answers, normalise


def sheet(*rows: tuple[str, list[str]]) -> list[dict]:
    return [{"name": key, "values": values} for key, values in rows]


# --- The projection ------------------------------------------------------
def test_every_answer_is_keyed_by_the_question_it_answers() -> None:
    """What ``field_data_raw`` cannot do. A list of objects has to be
    walked; this is a key lookup, in the database as well as here."""
    found = normalise(
        field_data=sheet(
            ("full_name", ["Aziz"]),
            ("q2", ["Chilonzor"]),
            ("q3", ["Ertalab"]),
        )
    )

    assert found.answers == {
        "full_name": ("Aziz",),
        "q2": ("Chilonzor",),
        "q3": ("Ertalab",),
    }


def test_a_multiple_choice_question_keeps_every_answer() -> None:
    """The four columns take the first answer on purpose - a name is one
    name. A question offering three boxes is the opposite case, and keeping
    one of the ticks would be losing the answer rather than tidying it."""
    found = normalise(field_data=sheet(("q2", ["Chilonzor", "Yunusobod"])))

    assert found.answers["q2"] == ("Chilonzor", "Yunusobod")


def test_the_columns_still_take_only_the_first() -> None:
    """The two rules live side by side and are different on purpose."""
    found = normalise(field_data=sheet(("full_name", ["Aziz", "Karimov"])))

    assert found.full_name == "Aziz"
    assert found.answers["full_name"] == ("Aziz", "Karimov")


def test_a_key_answered_twice_keeps_the_first() -> None:
    """A repeated field is the provider echoing something the person
    edited. Both are still in the raw payload, which is what makes dropping
    one here safe."""
    found = normalise(field_data=sheet(("q2", ["Chilonzor"]), ("q2", ["Sergeli"])))

    assert found.answers["q2"] == ("Chilonzor",)


def test_a_question_nobody_answered_is_left_out() -> None:
    """Skipped is not answered-with-nothing, and a key mapped to an empty
    list is the second thing pretending to be the first."""
    found = normalise(field_data=sheet(("q2", []), ("q3", ["  "])))

    assert found.answers == {}


def test_the_keys_are_the_providers_own_and_are_not_translated() -> None:
    """The vocabulary rule this whole shape rests on.

    A question is *sent* as a type - ``PHONE`` - and comes *back* under a
    field name - ``phone_number`` - and the two were never promised to
    match. Keying by what arrived is what makes that asymmetry harmless:
    there is no mapping table to keep up to date, and nothing that can be
    wrong about the key.
    """
    found = normalise(field_data=sheet(("phone_number", ["998901234567"])), region="UZ")

    assert "phone_number" in found.answers
    assert "PHONE" not in found.answers
    assert "phone" not in found.answers


# --- The pairing ---------------------------------------------------------
QUESTIONS = [
    {"type": "FULL_NAME", "key": "full_name"},
    {"type": "CUSTOM", "key": "q2", "label": "Qaysi tumandasiz?"},
]


def test_an_answer_is_shown_under_the_question_that_produced_it() -> None:
    rows = label_answers(field_data=sheet(("q2", ["Chilonzor"])), questions=QUESTIONS)

    assert [(row.label, row.values) for row in rows] == [
        ("Qaysi tumandasiz?", ("Chilonzor",))
    ]
    assert rows[0].is_labelled


def test_a_question_with_no_label_falls_back_to_its_key() -> None:
    """A standard question carries no wording of ours - the provider
    prefills and labels it in the person's own language. The key is poor
    labelling and is still something an owner can match against their form;
    a blank row would be an answer quietly dropped."""
    rows = label_answers(field_data=sheet(("full_name", ["Aziz"])), questions=QUESTIONS)

    assert rows[0].label == "full_name"
    assert not rows[0].is_labelled


def test_a_lead_from_a_form_nobody_mirrored_still_answers() -> None:
    """Normal rather than degraded: a form made before this product was
    connected collects leads all the same."""
    rows = label_answers(field_data=sheet(("q7", ["Ha"])))

    assert [(row.label, row.values) for row in rows] == [("q7", ("Ha",))]


def test_the_order_is_the_order_they_answered_in() -> None:
    """Answers walked, questions looked up - and not the other way round.

    A form can have more questions than this person answered: one they
    skipped, or a form edited into a new version after these leads arrived.
    Walking the questions would show empty rows for things nobody asked
    this person.
    """
    rows = label_answers(
        field_data=sheet(("q2", ["Chilonzor"]), ("full_name", ["Aziz"])),
        questions=QUESTIONS,
    )

    assert [row.key for row in rows] == ["q2", "full_name"]


# --- The wording of a picked option --------------------------------------
CHOICES = [
    {"type": "CUSTOM", "key": "q2", "label": "Qaysi tumandasiz?"},
    {
        "type": "CUSTOM",
        "key": "q3",
        "label": "Necha kishiga stol kerak?",
        "options": [
            {"key": "q3_o1", "value": "1-3 kishi"},
            {"key": "q3_o2", "value": "4-6 kishi"},
        ],
    },
]


def test_a_picked_option_is_shown_as_the_words_it_carried() -> None:
    """The answer arrives as the key of the option that was tapped, not as
    its wording. ``q3_o1`` under "Necha kishiga stol kerak?" is the question
    answered with an identifier, which is no answer to the one audience
    this screen has."""
    rows = label_answers(field_data=sheet(("q3", ["q3_o1"])), questions=CHOICES)

    assert [(row.label, row.values) for row in rows] == [
        ("Necha kishiga stol kerak?", ("1-3 kishi",))
    ]


def test_every_tick_on_a_multiple_choice_answer_is_spelled_out() -> None:
    """One answer can carry several keys, and half a translated row would
    read as two different kinds of answer to one question."""
    rows = label_answers(
        field_data=sheet(("q3", ["q3_o1", "q3_o2"])), questions=CHOICES
    )

    assert rows[0].values == ("1-3 kishi", "4-6 kishi")


def test_an_option_is_looked_up_under_its_own_question_only() -> None:
    """The keys are positional, so two questions key their first option the
    same way apart from the number that owns it. A form-wide table would
    answer one question with another question's wording - here ``q2`` has
    no options at all, and its typed answer must survive untouched."""
    rows = label_answers(
        field_data=sheet(("q2", ["q3_o1"]), ("q3", ["q3_o2"])), questions=CHOICES
    )

    assert [row.values for row in rows] == [("q3_o1",), ("4-6 kishi",)]


def test_an_answer_matching_no_option_is_kept_as_it_arrived() -> None:
    """Either a typed answer, which is already words, or an option this
    form does not describe. Inventing wording for the second would be worse
    than showing the key."""
    rows = label_answers(field_data=sheet(("q3", ["q3_o9"])), questions=CHOICES)

    assert rows[0].values == ("q3_o9",)


def test_options_with_no_keys_of_their_own_pass_through() -> None:
    """A form built by hand in Ads Manager usually has these, and the
    provider then sends the words themselves - already readable, and
    nothing to translate back."""
    questions = [
        {
            "type": "CUSTOM",
            "key": "q3",
            "label": "Necha kishiga stol kerak?",
            "options": [{"value": "1-3 kishi"}],
        }
    ]

    rows = label_answers(field_data=sheet(("q3", ["1-3 kishi"])), questions=questions)

    assert rows[0].values == ("1-3 kishi",)


def test_the_questions_may_be_walked_once_only() -> None:
    """A generator is a legitimate argument and a silent bug if it is
    walked twice: the label comes off the first walk and the options off a
    second one that finds nothing left, which is a labelled question with
    an unreadable answer."""
    rows = label_answers(
        field_data=sheet(("q3", ["q3_o2"])), questions=(row for row in CHOICES)
    )

    assert [(row.label, row.values) for row in rows] == [
        ("Necha kishiga stol kerak?", ("4-6 kishi",))
    ]


@pytest.mark.parametrize(
    "option",
    [
        pytest.param("1-3 kishi", id="a-bare-string"),
        pytest.param({"key": "q3_o1"}, id="no-wording"),
        pytest.param({"value": "1-3 kishi"}, id="no-key"),
    ],
)
def test_an_option_that_says_too_little_leaves_the_answer_alone(option: object) -> None:
    """A form somebody built by hand can describe its choices with
    anything, and a screen that raised over one of them would be a lead
    nobody can read."""
    questions = [{"type": "CUSTOM", "key": "q3", "options": [option]}]

    rows = label_answers(field_data=sheet(("q3", ["q3_o1"])), questions=questions)

    assert rows[0].values == ("q3_o1",)


@pytest.mark.parametrize(
    "row",
    [
        pytest.param({"name": "", "values": ["x"]}, id="no-key"),
        pytest.param({"name": "q2", "values": []}, id="no-values"),
        pytest.param({"name": "q2", "values": "Chilonzor"}, id="values-not-a-list"),
        pytest.param({"values": ["x"]}, id="nothing-at-all"),
    ],
)
def test_a_row_that_says_nothing_is_left_out(row: dict) -> None:
    """A lead form somebody built by hand can answer with anything, and a
    screen that raised over one malformed row would be a lead nobody can
    read."""
    assert label_answers(field_data=[row]) == ()
