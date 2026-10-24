"""videokit: the face found on a still, mapped into the frame, and kept clear."""

import io

import numpy as np
from PIL import Image
from videokit import (
    Brand,
    CaptionLine,
    CaptionWord,
    ComponentUse,
    Cut,
    EditSpec,
    build_edit,
)
from videokit.faces import _face, detect_faces, face_during, on_frame
from videokit.models import FaceMark
from videokit.preflight import preflight


def _jpeg(size: tuple[int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (90, 120, 150)).save(out, "JPEG")
    return out.getvalue()


def test_a_still_with_no_face_has_none_and_a_broken_one_too() -> None:
    assert detect_faces(_jpeg((360, 640))) == []
    assert detect_faces(b"not a picture") == []


def test_the_guard_is_drawn_round_the_eyes_and_the_mouth() -> None:
    # x, y, w, h, right eye, left eye, nose, mouth right, mouth left, score.
    row = np.array(
        [100, 200, 160, 200, 140, 280, 220, 280, 180, 320, 150, 360, 210, 360, 0.95],
        dtype=np.float32,
    )

    face = _face(row, 360, 640)

    left, top, right, bottom = face.guard
    assert top < 280 / 640 < 360 / 640 < bottom
    assert left < 140 / 360 and right > 220 / 360
    assert face.box == (
        round(100 / 360, 4),
        round(200 / 640, 4),
        round(260 / 360, 4),
        round(400 / 640, 4),
    )


def test_a_face_is_mapped_through_the_crop_and_the_zoom() -> None:
    # A wide still shows only its middle in a vertical frame.
    centre = on_frame((0.45, 0.4, 0.55, 0.6), still=(640, 360), aspect_ratio="9:16")
    closer = on_frame(
        (0.45, 0.4, 0.55, 0.6), still=(640, 360), aspect_ratio="9:16", zoom=1.2
    )

    assert 0 < centre[0] < 540 < centre[2] < 1080
    # Pushed in, the face grows away from the middle.
    assert closer[0] < centre[0] and closer[2] > centre[2]


def test_a_stretch_with_no_still_takes_the_nearest_close_by() -> None:
    marks = [FaceMark(at=2.0, box=(0, 0, 10, 100), guard=(0, 10, 10, 90))]

    assert face_during(marks, 2.5, 3.0) is not None
    assert face_during(marks, 8.0, 9.0) is None


def test_a_subtitle_over_the_mouth_stops_the_render() -> None:
    face = FaceMark(at=1.0, box=(330, 1150, 650, 1500), guard=(330, 1250, 640, 1450))
    line = CaptionLine(
        start=0.5, end=1.5, words=(CaptionWord(text="Salom", start=0.5, end=1.5),)
    )
    spec = EditSpec(
        source_url="https://example.test/v.mp4",
        cuts=(Cut(start=0, end=10),),
        resolution="1080",
        brand=Brand(name="Bahor", cta_text="Yozing"),
        captions=(line,),
        faces=(face,),
        components=(
            ComponentUse(name="hook_title", zone="TOP_TITLE", start=0, length=2,
                         props={"text": "Salom"}),
            ComponentUse(name="end_card", zone="FULL", start=7, length=3),
            ComponentUse(name="end_cta", zone="FULL", start=7.3, length=2.7),
        ),
    )  # fmt: skip

    moved = spec.model_copy(
        update={"captions": (line.model_copy(update={"top": 1000, "bottom": 1140}),)}
    )

    assert "face_covered" in [p.kind for p in preflight(spec, build_edit(spec))]
    assert "face_covered" not in [p.kind for p in preflight(moved, build_edit(moved))]


def test_lines_placed_all_over_share_one_clip_and_one_font() -> None:
    lines = tuple(
        CaptionLine(
            start=n * 1.0,
            end=n * 1.0 + 0.9,
            words=(CaptionWord(text=f"so'z{n}", start=n * 1.0, end=n * 1.0 + 0.9),),
            top=1000 + (n % 5) * 60,
            bottom=1150 + (n % 5) * 60,
            px=68 - (n % 3) * 4,
            scrim=n % 2 == 0,
        )
        for n in range(30)
    )
    spec = EditSpec(
        source_url="https://example.test/v.mp4",
        cuts=(Cut(start=0, end=31),),
        resolution="1080",
        captions=lines,
    )

    edit = build_edit(spec)
    clips = edit["timeline"]["tracks"][0]["clips"]

    assert len(clips) == 1
    assert clips[0]["asset"]["css"].count("@font-face") == 1
