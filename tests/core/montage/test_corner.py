"""The corner logo: shown while nothing else is at the top, in the copy
that reads on the footage behind it."""

from videokit import Brand, ComponentUse, Cut, LayoutSpan

from core.montage.corner import corner_logos, free_spans, output_time

# A logo this cannot measure is drawn in the corner's old box.
LOGO = Brand(logo="data:image/png;base64,T1dO")


def _use(name: str, zone: str, start: float, length: float) -> ComponentUse:
    return ComponentUse(name=name, zone=zone, start=start, length=length)  # type: ignore[arg-type]


HOOK = _use("hook_title", "TOP_TITLE", 0.5, 2.5)
NAME_BAR = _use("lower_third", "LOWER_THIRD", 4.0, 3.0)
END = _use("end_card", "FULL", 17.0, 3.0)
BUTTON = _use("cta_button", "LOWER_THIRD", 17.3, 2.7)


def test_it_steps_aside_for_the_top_of_the_frame_and_the_split() -> None:
    panel = _use("chips_list", "TOP_PANEL", 8.0, 4.0)
    split = LayoutSpan(start=8.0, end=12.0, layout="split_top")

    spans = free_spans(
        components=[HOOK, NAME_BAR, panel, END, BUTTON], layouts=[split], length=20.0
    )

    # Not under the headline, the panel or the end card, and not beside
    # the name bar's own logo; half a second before the headline is too
    # short to show.
    assert spans == [(3.0, 4.0), (7.0, 8.0), (12.0, 17.0)]


def test_a_split_alone_hides_it_too() -> None:
    split = LayoutSpan(start=2.0, end=5.0, layout="split_top")

    assert free_spans(components=[], layouts=[split], length=8.0) == [
        (0.0, 2.0),
        (5.0, 8.0),
    ]


def test_source_seconds_are_found_in_the_finished_video() -> None:
    cuts = [Cut(start=10.0, end=14.0), Cut(start=2.0, end=5.0)]

    assert output_time(cuts, 11.0) == 1.0
    assert output_time(cuts, 3.0) == 5.0
    assert output_time(cuts, 7.0) is None


def test_each_stretch_gets_the_copy_for_the_footage_behind_it() -> None:
    cuts = [Cut(start=0.0, end=20.0)]
    uses = corner_logos(
        components=[HOOK, _use("chips_list", "TOP_PANEL", 8.0, 4.0), END],
        layouts=[],
        cuts=cuts,
        # Light inside the first stretch, dark inside the second.
        brightness=[(5.0, 0.9), (6.0, 0.7), (14.0, 0.1)],
        brand=LOGO,
    )

    assert [(u.start, u.length, u.props) for u in uses] == [
        (3.0, 5.0, {"on_light": "1"}),
        (12.0, 5.0, {"on_dark": "1"}),
    ]
    assert {u.zone for u in uses} == {"CORNER"}


def test_a_stretch_with_no_still_inside_takes_the_nearest_or_dark() -> None:
    cuts = [Cut(start=0.0, end=10.0)]

    # The only still is under the end card, outside the stretch.
    near = corner_logos(
        components=[_use("end_card", "FULL", 8.0, 2.0)],
        layouts=[],
        cuts=cuts,
        brightness=[(9.5, 0.95)],
        brand=LOGO,
    )
    none = corner_logos(components=[], layouts=[], cuts=cuts, brightness=[], brand=LOGO)

    assert near[0].props == {"on_light": "1"}
    assert none[0].props == {"on_dark": "1"}


def test_one_light_still_in_a_stretch_makes_it_light() -> None:
    """A white logo is lost the moment the footage turns light."""
    cuts = [Cut(start=0.0, end=10.0)]

    uses = corner_logos(
        components=[],
        layouts=[],
        cuts=cuts,
        brightness=[(1.0, 0.1), (3.0, 0.15), (6.0, 0.7), (8.0, 0.1)],
        brand=LOGO,
    )

    assert uses[0].props == {"on_light": "1"}


def test_stretches_in_one_copy_are_one_clip_seen_only_in_them() -> None:
    """The logo is the heaviest thing a clip carries: it is sent once per copy."""
    cuts = [Cut(start=0.0, end=20.0)]
    uses = corner_logos(
        components=[HOOK, _use("chips_list", "TOP_PANEL", 8.0, 4.0), END],
        layouts=[],
        cuts=cuts,
        brightness=[(5.0, 0.1), (14.0, 0.1)],
        brand=LOGO,
    )

    assert len(uses) == 1
    assert (uses[0].start, uses[0].length) == (3.0, 14.0)
    assert uses[0].windows() == [(3.0, 8.0), (12.0, 17.0)]
