"""The live cases themselves: they load, they cover the plan's seven
situations, and the marks catch what they are for - checked here against
scripted answers, since the real model cannot run in a suite."""

from core.assistant.tools import TOOL_NAMES, with_reading
from core.evals.assistant import Run, canned, load, marks

PLANNED = {
    "payment-not-arrived",
    "account-blocked",
    "facebook-disconnected",
    "advert-refused",
    "leads-not-arriving",
    "off-topic",
    "wants-an-operator",
}


def test_the_seven_situations_are_all_cases() -> None:
    cases = load()
    assert {case.id for case in cases} == PLANNED
    for case in cases:
        assert set(case.tools) <= TOOL_NAMES, case.id
        assert set(case.must_call) <= TOOL_NAMES, case.id
        assert set(case.must_not_call) <= TOOL_NAMES, case.id
        assert not set(case.must_call) & set(case.must_not_call), case.id


def _case(name: str):  # type: ignore[no-untyped-def]
    return next(case for case in load() if case.id == name)


def test_a_good_answer_passes() -> None:
    case = _case("wants-an-operator")
    run = Run(
        answer="Albatta. Pastdagi tugma orqali so'rovingizni mutaxassisga jo'nating.",
        called=["create_ticket"],
    )
    assert all(mark.passed for mark in marks(case, run))


def test_saying_it_was_sent_fails() -> None:
    case = _case("wants-an-operator")
    run = Run(
        answer="Mutaxassisga yubordim, tugma kerak emas.", called=["create_ticket"]
    )
    failed = [mark.check for mark in marks(case, run) if not mark.passed]
    assert failed == ["no_forbidden_words"]


def test_a_tool_not_called_or_called_wrongly_fails() -> None:
    case = _case("facebook-disconnected")
    run = Run(
        answer="Ulanish uzilgan.\n1. Ulanishlar sahifasini oching.",
        called=["create_ticket"],
    )
    failed = {mark.check for mark in marks(case, run) if not mark.passed}
    assert failed == {"called_what_it_must", "called_nothing_it_must_not"}


def test_a_figure_from_a_canned_result_is_not_invented() -> None:
    case = _case("payment-not-arrived")
    run = Run(
        answer="INV-1042 hisobi (290 000 UZS) hali ochiq. Pastdagi tugma bilan mutaxassisga jo'nating.",
        called=["account_health", "create_ticket"],
    )
    by = {mark.check: mark for mark in marks(case, run)}
    assert by["no_invented_figures"].passed, by["no_invented_figures"].detail


def test_a_canned_result_arrives_with_its_reading_note() -> None:
    case = _case("leads-not-arriving")
    answer = canned(case, reading=with_reading)

    assert answer("account_health").startswith("How to read this:")
    assert "nothing has been sent" in answer("create_ticket")
    assert answer("find").endswith("nothing found.")
