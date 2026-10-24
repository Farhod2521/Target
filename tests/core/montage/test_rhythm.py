"""Something new on screen every few seconds: punch-ins in the quiet
stretches, and a burst where the video moves on to a new part."""

from itertools import pairwise

from videokit import ComponentUse, Cut

from core.montage import SpokenWord
from core.montage.plan import PlanSegmentV3
from core.montage.rhythm import MAX_QUIET, lively_punches
from core.montage.settle import MOST_CHANGES, section_changes


def _words(count: int) -> tuple[SpokenWord, ...]:
    return tuple(
        SpokenWord(text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(count)
    )


def test_a_long_quiet_stretch_gets_a_punch_in_near_its_middle() -> None:
    cuts = [Cut(start=0.0, end=20.0)]
    hook = ComponentUse(name="hook_title", zone="TOP_TITLE", start=0.0, length=2.5)
    card = ComponentUse(name="end_card", zone="FULL", start=17.0, length=3.0)

    punches = lively_punches((), components=[hook, card], cuts=cuts, words=_words(40))

    moments = sorted({0.0, 17.0, *punches})
    assert punches
    assert all(b - a <= MAX_QUIET for a, b in pairwise(moments))


def test_a_busy_video_is_left_as_it_is() -> None:
    cuts = [Cut(start=0.0, end=3.0), Cut(start=5.0, end=8.0), Cut(start=10.0, end=13.0)]

    assert lively_punches((2.0,), components=[], cuts=cuts, words=_words(28)) == (2.0,)


def test_a_new_part_bursts_in_unless_the_plan_said_otherwise() -> None:
    roles = ["hook", "body", "body", "proof", "offer", "cta", "cta"]
    segments = [
        PlanSegmentV3(start=i, end=i + 1, role=role)  # type: ignore[arg-type]
        for i, role in enumerate(roles)
    ]
    segments[3] = segments[3].model_copy(update={"transition_in": "fade"})

    enters = section_changes(segments)

    assert enters[0] == "none" and enters[2] == "none"
    assert enters[1] == "burst" and enters[3] == "fade"
    assert sum(e != "none" for e in enters) == MOST_CHANGES
