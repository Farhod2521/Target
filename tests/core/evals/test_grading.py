"""Marking an answer, without asking anybody anything.

The run itself costs money and talks to Anthropic, so it is a command
somebody starts by hand and never a test - see
``apps.audit.management.commands.evaluate_prompts``. What *is* testable is
the half that decides whether an answer was acceptable, and it has to be:
a grader that passes everything reports a perfect model for ever.
"""

import json

from core.evals import Case, grade, load_cases
from core.evals.cases import CASES_DIR
from core.evals.grade import Report


def a_case(**overrides: object) -> Case:
    fields: dict[str, object] = {
        "id": "one",
        "surface": "chat",
        "prompt": "chat_answer",
        "question": "Qancha sarfladim?",
        "context": "## Last 30 days\n- Spend: 412 USD\n- Results: 38 murojaat",
    }
    return Case(**(fields | overrides))  # type: ignore[arg-type]


def marks(case: Case, answer: str) -> dict[str, bool]:
    return {mark.check: mark.passed for mark in grade(case=case, answer=answer)}


# --- what the graders catch -----------------------------------------------


def test_a_figure_the_context_never_gave_is_caught() -> None:
    """The check that matters most, and it is the live gate: a figure that
    fails here is one a customer would have seen as a marker."""
    found = marks(a_case(), "O'tgan oyda 900 USD sarfladingiz.")

    assert found["no_invented_figures"] is False


def test_a_figure_the_context_gave_is_not() -> None:
    found = marks(a_case(), "O'tgan oyda 412 USD sarfladingiz, 38 ta murojaat keldi.")

    assert found["no_invented_figures"] is True


def test_a_forbidden_word_is_caught_whatever_apostrophe_it_carries() -> None:
    """The words in question are Uzbek and arrive with whichever apostrophe
    a phone keyboard produced."""
    case = a_case(forbidden=("o'zgartiring",))

    curly = "Auditoriyani o" + "\N{LEFT SINGLE QUOTATION MARK}" + "zgartiring."

    assert marks(case, curly)["no_forbidden_words"] is False
    assert marks(case, "Hammasi joyida.")["no_forbidden_words"] is True


def test_an_answer_that_never_reaches_the_point_is_caught() -> None:
    case = a_case(required=("rasm", "video"))

    assert marks(case, "Matnni qayta yozing.")["says_what_it_must"] is False
    assert marks(case, "Yangi rasm qo'ying.")["says_what_it_must"] is True


def test_a_case_that_requires_nothing_passes_that_check() -> None:
    assert marks(a_case(), "Salom.")["says_what_it_must"] is True


def test_an_answer_in_the_wrong_script_is_caught() -> None:
    """Latin where the screens are Latin. Anything finer than the script
    would be a second language model."""
    assert marks(a_case(), "Вы потратили 412 USD.")["right_script"] is False


def test_a_russian_case_is_not_failed_for_being_russian() -> None:
    assert marks(a_case(language="ru"), "Вы потратили 412 USD.")["right_script"] is True


def test_an_empty_answer_fails_rather_than_passing_everything() -> None:
    """It breaks no rule, which is exactly why it has to be its own check."""
    found = marks(a_case(required=("rasm",)), "   ")

    assert found["answered"] is False


# --- the report ------------------------------------------------------------


def test_a_report_names_only_the_checks_that_failed() -> None:
    case = a_case(required=("rasm",))
    report = Report(
        case_id=case.id,
        surface=case.surface,
        answer="900 USD sarfladingiz.",
        marks=grade(case=case, answer="900 USD sarfladingiz."),
    )

    assert report.passed is False
    assert set(report.failures) == {"no_invented_figures", "says_what_it_must"}


# --- the cases on disk ----------------------------------------------------


def test_every_case_file_loads() -> None:
    """A case file is JSON somebody edits by hand, and a run that fell over
    on the third one would have spent the first two."""
    assert load_cases()


def test_every_case_has_an_id_of_its_own() -> None:
    """The id is what a result row is read by and what ``--case`` selects."""
    ids = [case.id for case in load_cases()]

    assert len(ids) == len(set(ids))


def test_every_case_carries_the_account_it_is_asked_about() -> None:
    """The allow-set is derived from the context, so a case without one
    marks every figure in the answer as invented."""
    assert all(case.context.strip() for case in load_cases())


def test_no_case_names_a_surface_that_is_not_its_file() -> None:
    for path in sorted(CASES_DIR.glob("*.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))

        assert rows, path
        assert all("surface" not in row for row in rows), path


def test_a_hyphen_standing_in_for_a_dash_is_caught() -> None:
    """The one mark the model reaches for by itself.

    Every screen beside this answer separates with the long dash, and
    between two figures a hyphen is read as a subtraction - which is the
    reason this is graded rather than left to taste.
    """
    found = marks(a_case(), "«Bahor» - 45 USD sarfladi.")

    assert found["house_style"] is False
    assert marks(a_case(), "«Bahor» — 45 USD sarfladi.")["house_style"] is True


def test_a_table_in_a_chat_answer_is_caught() -> None:
    """Rows replaced it, on both surfaces, for the same reason: a phone."""
    table = "| Nom | Sarf |\n|---|---|\n| «Bahor» | 45 USD |"

    assert marks(a_case(), table)["house_style"] is False


def test_the_marks_are_only_asked_of_the_surface_that_has_them() -> None:
    """The night's own prompts were not given these rules, and grading a
    surface against rules it was never handed measures nothing."""
    case = a_case(surface="daily", prompt="daily_report")

    assert marks(case, "Kecha yaxshi o'tmadi - sarf bor, natija yo'q.")["house_style"]


def test_a_hyphen_inside_a_name_is_the_rule_kept_not_broken() -> None:
    """The account called it that, and the prompt says to copy it.

    Marked as a fault, this would score the model down for the one thing
    it must never do to a name: tidy it.
    """
    found = marks(a_case(), "«Guldasta - mart» guruhida sabab aniqlandi.")

    assert found["house_style"] is True


def test_a_name_in_straight_quotes_is_caught() -> None:
    """A name in "these" beside a screen in "these" leaves the reader
    working out which of the two is theirs."""
    assert marks(a_case(), '"Soch olish" e\'loni ishlayapti.')["house_style"] is False


def test_an_english_word_for_something_with_an_uzbek_one_is_caught() -> None:
    """From a real run: "hozircha faol reklama campaign ishlamayapti"."""
    found = marks(a_case(), "Hozircha faol reklama campaign ishlamayapti.")

    assert found["house_style"] is False
    assert marks(a_case(), "Hozircha faol kampaniya yo'q.")["house_style"] is True


def test_a_screen_inside_the_brackets_is_caught() -> None:
    """«Reklama» is a campaign somebody called Reklama.

    Which an account can genuinely have - so the brackets are what tells
    the screen and the campaign apart, and a screen put inside them takes
    that apart for every name in the answer.
    """
    assert marks(a_case(), "Buni «Reklama» ekranida qiling.")["house_style"] is False
    assert marks(a_case(), "Buni Reklama ekranida qiling.")["house_style"] is True


def test_the_platforms_neutral_label_is_caught_in_any_alphabet() -> None:
    """Told never to write "provider", a run wrote "provayder bahosi".

    The rule kept as an English word and broken as an Uzbek one, to
    somebody whose screens all say Meta - and in Uzbek it reads as the
    company that sells them internet.
    """
    assert marks(a_case(), "Provayder bahosi past.")["house_style"] is False
    assert marks(a_case(), "The provider rates it low.")["house_style"] is False
    assert marks(a_case(), "Meta bu reklamani past baholaydi.")["house_style"] is True


def test_a_figure_the_question_itself_carried_is_not_invented() -> None:
    """Both surfaces allow it, so the grader has to.

    The cabinet passes the figures the person typed; the night passes the
    shortlist it is being asked about. A note quoting the entry it was
    handed is the rule kept, not broken.
    """
    case = a_case(question="Reklama guruhi 45 USD sarfladi, murojaat yo'q.")

    assert marks(case, "45 USD sarflandi va murojaat kelmadi.")["no_invented_figures"]
