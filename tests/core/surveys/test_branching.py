"""Which questions are asked for the picks so far, and which rules stand."""

from core.surveys import Rule, asked_positions, rule_problem

# The office's example: 1 - advertised before?; 2 - how did it go (only
# for "yes, myself" or "yes, through a targetologist"); 3 - plain; 4 - the
# quality; 5 - why they do not buy (option 1 of 4); 6 - why junk (option
# 2 of 4).
SURVEY = [
    Rule(1),
    Rule(2, parent=1, options=(0, 1)),
    Rule(3),
    Rule(4),
    Rule(5, parent=4, options=(1,)),
    Rule(6, parent=4, options=(2,)),
]


def test_nothing_picked_asks_only_the_plain_questions() -> None:
    assert asked_positions(SURVEY, {}) == [1, 3, 4]


def test_a_pick_opens_the_question_hung_on_it() -> None:
    assert asked_positions(SURVEY, {1: [1], 4: [2]}) == [1, 2, 3, 4, 6]


def test_another_pick_keeps_it_closed() -> None:
    assert asked_positions(SURVEY, {1: [2], 4: [0]}) == [1, 3, 4]


def test_a_closed_question_closes_what_hangs_on_it() -> None:
    chain = [Rule(1), Rule(2, parent=1, options=(0,)), Rule(3, parent=2, options=(0,))]

    assert asked_positions(chain, {1: [1], 2: [0]}) == [1]
    assert asked_positions(chain, {1: [0], 2: [0]}) == [1, 2, 3]


def test_several_picks_open_on_any_of_them() -> None:
    assert asked_positions(SURVEY, {4: [0, 1]}) == [1, 3, 4, 5]


def test_a_rule_must_look_back_at_a_choice_and_its_options() -> None:
    def problem(parent: int, options: list[int], count: int = 3) -> str:
        return rule_problem(
            position=3, parent=parent, options=options, parent_options=count
        )

    assert problem(0, []) == ""
    assert problem(1, [0, 2]) == ""
    assert problem(3, [0]) == "later"
    assert problem(4, [0]) == "later"
    assert problem(1, [0], count=-1) == "kind"
    assert problem(1, []) == "options"
    assert problem(1, [3]) == "options"
