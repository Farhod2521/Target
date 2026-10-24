"""The words a plan marks as the point become moments to punch in on."""

from videokit import Cut

from core.montage import SpokenWord
from core.montage.emphasis import punch_times
from core.montage.plan import plan_schema

WORDS = tuple(
    SpokenWord(text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(20)
)


def test_a_marked_word_punches_in_where_it_plays_in_the_finished_video() -> None:
    cuts = (Cut(start=5.0, end=8.0), Cut(start=0.0, end=3.0))

    # w12 starts at 6.0 in the source, 1.0 into the finished video;
    # w2 starts at 1.0 in the source, after the first cut's 3 seconds.
    assert punch_times([2, 12], words=WORDS, cuts=cuts) == (1.0, 4.0)


def test_a_word_that_was_cut_out_is_let_go() -> None:
    assert punch_times([15], words=WORDS, cuts=(Cut(start=0, end=3),)) == ()


def test_two_marks_close_together_are_one() -> None:
    cuts = (Cut(start=0, end=10),)

    assert punch_times([4, 5, 9], words=WORDS, cuts=cuts) == (2.0, 4.5)


def test_the_plan_holds_marks_to_the_transcript() -> None:
    schema = plan_schema(word_count=3)

    plan = schema.model_validate(
        {"segments": [{"start": 0, "end": 1}], "emphasis": [2], "summary": "-"}
    )

    assert plan.emphasis == [2]
    assert "emphasis" in schema.model_json_schema()["properties"]
