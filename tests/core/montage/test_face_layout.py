"""Graphics and subtitles moved off the speaker's face."""

import pytest
from videokit import ComponentUse, Cut, LayoutSpan
from videokit.faces import meets
from videokit.models import FaceMark

from core.montage.captions import Line, SpokenWord
from core.montage.face_layout import MAX_SPLIT, arrange
from core.montage.faces import face_marks

# The test clip's face: box from the forehead to the chin, guard round the
# eyes and the mouth (design pixels, as measured on the stage render).
FACE = FaceMark(at=0.0, box=(330, 850, 650, 1290), guard=(330, 945, 640, 1215))
HIGH = FaceMark(at=0.0, box=(330, 400, 650, 840), guard=(330, 495, 640, 765))


def _marks(face: FaceMark, until: float = 20.0) -> list[FaceMark]:
    return [face.model_copy(update={"at": float(t)}) for t in range(int(until) + 1)]


def _bar(start: float = 3.0) -> ComponentUse:
    return ComponentUse(name="lower_third", zone="LOWER_THIRD", start=start, length=4)


def _line(start: float, text: str = "Biz yaqinda startap boshladik") -> Line:
    words = tuple(
        SpokenWord(text=w, start=start + n * 0.3, end=start + n * 0.3 + 0.25)
        for n, w in enumerate(text.split())
    )
    return Line(start=start, end=words[-1].end, text=text, words=words)


def _content(use: ComponentUse) -> tuple[float, float, float, float]:
    top = use.top if use.top is not None else 1060
    return (48, top + 20, 940, top + 220)


def test_with_no_face_everything_stays_where_it_is() -> None:
    placed = arrange(
        components=[_bar()], layouts=[], lines=[_line(1)], marks=[], font="bold"
    )

    assert placed.components == (_bar(),) and placed.captions == (None,)


def test_the_name_bar_goes_over_the_head_when_the_chin_leaves_no_room() -> None:
    placed = arrange(
        components=[_bar()], layouts=[], lines=[], marks=_marks(FACE), font="bold"
    )

    bar = placed.components[0]
    assert bar.top is not None and _content(bar)[3] <= FACE.box[1]
    assert not meets(_content(bar), FACE.box)


def test_the_name_bar_goes_under_the_chin_when_the_face_is_high() -> None:
    placed = arrange(
        components=[_bar()], layouts=[], lines=[], marks=_marks(HIGH), font="bold"
    )

    bar = placed.components[0]
    # Under the chin it fits where it always sits.
    assert bar.top is None and _content(bar)[1] >= HIGH.box[3]


def test_a_panel_moves_the_footage_just_below_it_or_goes() -> None:
    chips = ComponentUse(
        name="chips_list", zone="TOP_PANEL", start=8, length=4,
        props={"items": ["Bir", "Ikki"]},
    )  # fmt: skip
    split = LayoutSpan(start=8, end=12, layout="split_top")

    fits = arrange(
        components=[chips], layouts=[split], lines=[], marks=_marks(FACE), font="bold"
    )
    too_high = FaceMark(at=0, box=(330, 200, 650, 400), guard=(330, 220, 640, 380))
    goes = arrange(
        components=[chips], layouts=[split], lines=[], marks=_marks(too_high),
        font="bold",
    )  # fmt: skip

    shift = fits.layouts[0].shift
    assert shift is not None and 0 < shift * 1920 <= MAX_SPLIT
    # The eyes land under the panel's bottom edge.
    margin = (FACE.box[3] - FACE.box[1]) * 0.1
    assert FACE.guard[1] - margin + shift * 1920 >= 960
    assert goes.components == () and goes.layouts == ()
    assert goes.notes and "panel" in goes.notes[0]
    assert goes.dropped == (chips,) and fits.dropped == ()


def test_a_subtitle_goes_under_the_chin_and_shrinks_to_fit_there() -> None:
    placed = arrange(
        components=[], layouts=[], lines=[_line(10)], marks=_marks(FACE), font="bold"
    )

    top, bottom, px = placed.captions[0]  # type: ignore[misc]
    assert top >= FACE.box[3] and bottom <= 1500
    assert 44 <= px <= 68


def test_a_subtitle_and_a_name_bar_at_once_share_the_room_off_the_face() -> None:
    placed = arrange(
        components=[_bar(3)], layouts=[], lines=[_line(3.5)], marks=_marks(FACE),
        font="bold",
    )  # fmt: skip

    bar = placed.components[0]
    top, bottom, _px = placed.captions[0]  # type: ignore[misc]
    caption = (140, top, 940, bottom)
    assert not meets(caption, _content(bar))
    assert not meets(caption, FACE.guard)


# A face so low and so big that under the mouth only one row fits.
LOW = FaceMark(at=0.0, box=(300, 820, 680, 1430), guard=(300, 940, 670, 1370))


def test_a_line_too_tall_for_the_room_is_split_in_two() -> None:
    long = _line(10, "Endi bu startapni dunyo bozoriga olib chiqmoqchimiz")

    # A headline up meanwhile takes the room over the head.
    hook = ComponentUse(
        name="hook_title", zone="TOP_TITLE", start=9, length=3, props={"text": "Salom"}
    )

    placed = arrange(
        components=[hook], layouts=[], lines=[long], marks=_marks(LOW), font="bold"
    )

    assert len(placed.lines) == 2
    assert " ".join(line.text for line in placed.lines) == long.text
    assert all(place is not None for place in placed.captions)
    assert placed.lines[0].end <= placed.lines[1].start


def test_a_panel_with_no_room_for_the_subtitles_goes() -> None:
    chips = ComponentUse(
        name="chips_list", zone="TOP_PANEL", start=8, length=4,
        props={"items": ["Bir", "Ikki"]},
    )  # fmt: skip
    split = LayoutSpan(start=8, end=12, layout="split_top")
    # The eyes just under the panel's edge: the split moves the mouth down
    # to the bottom of the safe area.
    tight = FaceMark(at=0.0, box=(300, 960, 680, 1490), guard=(300, 990, 670, 1440))

    placed = arrange(
        components=[chips], layouts=[split], lines=[_line(9)], marks=_marks(tight),
        font="bold",
    )  # fmt: skip

    assert placed.components == () and placed.layouts == ()
    assert any("no room for subtitles" in note for note in placed.notes)
    assert placed.dropped == (chips,)


def test_a_mark_grows_about_the_face_itself_as_the_picture_pushes_in() -> None:
    """The zoom is held on the face, so the face stays where it is and
    only grows - the mark covers it at the least zoom and at the most."""
    stored_face = [2.0, 540, 960, [0.3, 0.4, 0.6, 0.7], [0.35, 0.45, 0.55, 0.65], 0.9]
    cuts = [Cut(start=0.0, end=10.0)]

    plain = face_marks([stored_face], cuts=cuts, aspect_ratio="9:16")[0]
    punched = face_marks([stored_face], cuts=cuts, aspect_ratio="9:16", punches=(1.5,))[
        0
    ]

    middle = (
        (plain.guard[0] + plain.guard[2]) / 2,
        (plain.guard[1] + plain.guard[3]) / 2,
    )
    assert (punched.guard[0] + punched.guard[2]) / 2 == pytest.approx(middle[0], abs=1)
    assert (punched.guard[1] + punched.guard[3]) / 2 == pytest.approx(middle[1], abs=1)
    assert punched.guard[2] - punched.guard[0] > plain.guard[2] - plain.guard[0]
