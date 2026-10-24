"""Which frames of the finished video are looked at."""

from videokit import ComponentUse

from core.montage.review import FEWEST, MOST, Review, ReviewIssue, keyframes


def _use(name: str, start: float, length: float) -> ComponentUse:
    zone = {"end_card": "FULL", "corner_logo": "CORNER"}.get(name, "LOWER_THIRD")
    return ComponentUse(name=name, zone=zone, start=start, length=length)  # type: ignore[arg-type]


def test_each_component_is_seen_in_its_middle_and_the_card_before_the_end() -> None:
    uses = [
        ComponentUse(name="hook_title", zone="TOP_TITLE", start=0, length=2),
        _use("lower_third", 3, 4),
        _use("corner_logo", 2, 20),
        _use("end_card", 27, 3),
        _use("cta_button", 27.3, 2.7),
    ]

    frames = keyframes(uses, length=30)

    assert [f.at for f in frames][:2] == [1.0, 5.0]
    assert any(f.at == 29.4 and "closing card" in f.shows for f in frames)
    assert not any("corner" in f.shows for f in frames)
    assert FEWEST <= len(frames) <= MOST
    assert [f.at for f in frames] == sorted(f.at for f in frames)


def test_moments_close_together_are_one_frame() -> None:
    uses = [_use("lower_third", 3, 2), _use("cta_button", 3.2, 1.8)]

    frames = keyframes(uses, length=10)

    shared = [f for f in frames if "name bar" in f.shows]
    assert len(shared) == 1 and "call-to-action" in shared[0].shows


def test_many_components_are_thinned_to_the_most_with_the_card_kept() -> None:
    uses = [_use("lower_third", n * 3.0, 2.0) for n in range(12)]
    uses.append(_use("end_card", 40, 3))

    frames = keyframes(uses, length=43)

    assert len(frames) == MOST
    assert "closing card" in frames[-1].shows


def test_only_a_high_finding_needs_a_person() -> None:
    low = ReviewIssue(t=1, type="other", severity="medium", note="x")
    high = ReviewIssue(t=1, type="black_frame", severity="high", note="x")

    assert not Review(issues=[low]).needs_a_person
    assert Review(issues=[low, high]).needs_a_person


def test_a_frame_is_not_taken_while_a_subtitle_line_fades_in() -> None:
    uses = [_use("lower_third", 3, 4)]

    frames = keyframes(uses, length=30, line_starts=[4.95])

    assert 5.0 not in [f.at for f in frames]
    assert 5.15 in [f.at for f in frames]


def test_a_late_moment_is_looked_at_after_it_lands() -> None:
    """Before the label slams down, a frame shows the headline unfinished."""
    slam = ComponentUse(
        name="headline_slam", zone="TOP_TITLE", start=19.0, length=3.0,
        props={"pill": "IMKONSIZ"}, beats={"slam": 20.9},
    )  # fmt: skip

    frames = keyframes([slam], length=30)

    looked = next(f.at for f in frames if "slammed" in f.shows)
    assert 21.5 <= looked <= 21.6
