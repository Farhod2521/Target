"""A v3 plan all the way to Shotstack's JSON, compared with a stored copy.

The copy is the review: a change to placement, layout, a component or the
edit shows up as a diff of ``snapshots/*.json``. After a deliberate change,
write the copies again with ``UPDATE_SNAPSHOTS=1 uv run pytest <this file>``
and read the diff before committing it.

Each clip's font is cut to its own letters and written as ``<font>``; a
logo is a few bytes standing for one.

The three Brand Faces at the end are the ones the brand work was checked
with by eye: a café with a pink accent whose logo spells its whole name, a
plov centre with an orange accent and a phone, a gym whose logo says only
part of its name.
"""

import base64
import io
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw
from videokit import (
    Brand,
    CaptionLine,
    CaptionWord,
    ComponentUse,
    Cut,
    EditSpec,
    build_edit,
    edit_bytes,
)
from videokit.components import components
from videokit.sounds import sounds

from core.montage import SpokenWord, lines_for
from core.montage.corner import corner_logos
from core.montage.plan import plan_schema
from core.montage.settle import settle_v3

SNAPSHOTS = Path(__file__).parent / "snapshots"
_FONT = re.compile(r"@font-face\{font-family:'Brand';[^}]*\}")
BRAND = Brand(
    primary="#0f766e",
    accent="#f59e0b",
    name="Bahor gullari",
    tagline="Har kuni yangi guldastalar",
    cta_text="Telegram",
    cta_handle="@bahor_gul",
)
SAID = (
    "Bugun barcha guldastalarga yigirma foiz chegirma! Bizda yetkazib berish "
    "tez, guldastalar yangi, narxlar arzon. Buyurtma uchun Telegramga yozing."
)


def _words() -> tuple[SpokenWord, ...]:
    return tuple(
        SpokenWord(
            text=text, start=round(0.3 + i * 0.45, 2), end=round(0.65 + i * 0.45, 2)
        )
        for i, text in enumerate(SAID.split())
    )


def _edit(
    plan: dict[str, Any],
    *,
    brand: Brand = BRAND,
    brightness: tuple[tuple[float, float], ...] = (),
) -> dict[str, Any]:
    words = _words()
    settled = settle_v3(
        plan=plan_schema(word_count=len(words)).model_validate(plan),
        source_seconds=12.0,
        target_seconds=30,
        words=words,
        brand=brand,
    )
    uses = settled.components
    if brand.show_corner_logo and brand.logo:
        uses += corner_logos(
            components=settled.components,
            layouts=settled.layouts,
            cuts=settled.cuts,
            brightness=brightness,
            brand=brand,
        )
    lines = lines_for(words=words, cuts=settled.cuts)
    spec = EditSpec(
        source_url="https://example.test/source.mp4",
        cuts=settled.cuts,
        resolution="1080",
        brand=brand,
        components=uses,
        layouts=settled.layouts,
        motion="moving",
        punches=settled.punches,
        tail=settled.tail,
        tail_from=settled.cuts[-1].end,
        sound_urls={name: f"https://example.test/{name}.mp3" for name in sounds()},
        captions=tuple(
            CaptionLine(
                start=line.start,
                end=line.end,
                words=tuple(
                    CaptionWord(text=w.text, start=w.start, end=w.end)
                    for w in line.words
                ),
            )
            for line in lines
        ),
    )
    return json.loads(_FONT.sub("<font>", json.dumps(build_edit(spec))))


def _matches(name: str, edit: dict[str, Any]) -> None:
    path = SNAPSHOTS / f"{name}.json"
    text = json.dumps(edit, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") or not path.exists():
        path.write_text(text, encoding="utf-8")
        if not os.environ.get("UPDATE_SNAPSHOTS"):
            pytest.fail(f"{path.name} was missing and has been written; run again")
    assert text == path.read_text(encoding="utf-8")


def test_a_plan_with_a_headline_a_panel_and_a_name_bar() -> None:
    _matches(
        "plan_v3_full",
        _edit(
            {
                "segments": [
                    {"start": 0.0, "end": 4.0, "role": "hook"},
                    {"start": 4.0, "end": 9.0, "role": "body", "layout": "split_top",
                     "transition_in": "slide"},
                    {"start": 9.0, "end": 12.0, "role": "cta", "framing": "close",
                     "transition_in": "flash"},
                ],
                "emphasis": [3, 13],
                "events": [
                    {"component": "hook_title", "anchor_word": 0, "until_word": 4,
                     "props": {"text": "20% chegirma bugun!"}},
                    {"component": "chips_list", "anchor_word": 9, "until_word": 17,
                     "props": {"title": "Nega biz?", "items": ["Tez yetkazish",
                               "Yangi gullar", "Arzon narx"]}},
                ],
                "summary": "Chegirma, afzalliklar va buyurtma.",
            }
        ),
    )  # fmt: skip


def test_a_plan_with_no_graphics_still_gets_a_headline_and_a_close() -> None:
    _matches(
        "plan_v3_bare",
        _edit(
            {
                "segments": [{"start": 0.0, "end": 12.0}],
                "events": [],
                "summary": "Butun video.",
            }
        ),
    )


FACES = {
    "bahor_kafesi": Brand(
        primary="#5b1a8c",
        accent="#f0509b",
        text="#ffffff",
        name="Bahor kafesi",
        tagline="Nonushta va shirinliklar",
        cta_text="Yozing",
        cta_handle="@bahor_kafe",
        cta_phone="+12025550101",
        logo="data:image/png;base64,QkFIT1I=",
        logo_on_dark="data:image/png;base64,QkFIT1ItZGFyaw==",
        logo_on_light="data:image/png;base64,QkFIT1ItbGlnaHQ=",
        font="friendly",
        show_corner_logo=True,
        name_in_logo=True,
    ),
    "osh_markazi": Brand(
        primary="#6b2e0e",
        accent="#e8731a",
        text="#ffffff",
        name="Osh Markazi",
        cta_text="Buyurtma bering",
        cta_handle="@osh_markazi",
        cta_phone="+12025550102",
        logo="data:image/png;base64,T1NI",
        logo_on_dark="data:image/png;base64,T1NILWRhcms=",
        font="modern",
        show_corner_logo=True,
        name_in_logo=True,
    ),
    "chilonzor_fitnes": Brand(
        primary="#0f172a",
        accent="#22c55e",
        text="#ffffff",
        name="Chilonzor Fitnes",
        tagline="Zamonaviy zal",
        cta_text="Yoziling",
        cta_handle="@chilonzor.fitnes",
        logo="data:image/png;base64,Q0hJTA==",
        logo_on_dark="data:image/png;base64,Q0hJTC1kYXJr",
        font="bold",
        show_corner_logo=True,
        name_in_logo=False,
    ),
}
FACE_PLAN = {
    "segments": [
        {"start": 0.0, "end": 4.0, "role": "hook"},
        {"start": 4.0, "end": 12.0, "role": "body", "transition_in": "slide"},
    ],
    "emphasis": [3],
    "events": [
    ],
    "summary": "Taklif va buyurtma.",
}  # fmt: skip


@pytest.mark.parametrize("face", sorted(FACES))
def test_each_brand_face_draws_its_own_video(face: str) -> None:
    """The corner logo waits out the headline and the name bar, and shows
    over light footage in the light copy - or the logo's own, where the
    brand has none."""
    edit = _edit(FACE_PLAN, brand=FACES[face], brightness=((1.0, 0.2), (7.0, 0.8)))

    _matches(f"face_{face}", edit)


# --- Size ----------------------------------------------------------------------
# Shotstack refuses an edit over 390 KB. A minute of video with twenty
# graphics, subtitles throughout and a real logo stays well under it.
TWENTY_LIMIT = 250_000


def _logo() -> str:
    """A 256 px logo of the kind an upload is made into, about 6 KB."""
    image = Image.new("RGBA", (256, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for i in range(24):
        draw.ellipse((i * 10, (i * 37) % 90, i * 10 + 40, (i * 37) % 90 + 36),
                     fill=(30 + i * 9, 200 - i * 5, 90 + i * 6, 255))  # fmt: skip
    out = io.BytesIO()
    image.save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def test_twenty_graphics_and_a_minute_of_subtitles_fit_well_under_the_limit() -> None:
    logo = _logo()
    brand = FACES["chilonzor_fitnes"].model_copy(
        update={"logo": logo, "logo_on_dark": logo, "logo_on_light": logo}
    )
    planned = [c for c in components().values() if c.placement == "planner"]
    uses = [
        ComponentUse(
            name=item.name,
            zone=item.zones[0],
            start=round(i * 2.8, 3),
            length=item.min_seconds,
            props=item.example,
        )
        for i, item in enumerate(planned[i % len(planned)] for i in range(20))
    ]
    uses += [
        ComponentUse(name="end_card", zone="FULL", start=57.0, length=3.0),
        ComponentUse(name="end_cta", zone="FULL", start=57.3, length=2.7),
        # The corner logo between the graphics, one clip seen five times.
        ComponentUse(name="corner_logo", zone="CORNER", start=2.0, length=41.5,
                     props={"on_dark": "1"},
                     beats={"shows": [2.0, 3.5, 12.0, 13.5, 22.0, 23.5, 32.0,
                                      33.5, 42.0, 43.5]}),
    ]  # fmt: skip
    said = (SAID + " ") * 6
    words = [
        CaptionWord(text=w, start=round(i * 0.4, 2), end=round(i * 0.4 + 0.35, 2))
        for i, w in enumerate(said.split())
    ]
    spec = EditSpec(
        source_url="https://example.test/source.mp4",
        cuts=(Cut(start=0.0, end=60.0),),
        resolution="1080",
        brand=brand,
        components=tuple(uses),
        motion="moving",
        captions=tuple(
            CaptionLine(start=words[i].start, end=words[i + 4].end,
                        words=tuple(words[i : i + 5]))
            for i in range(0, len(words) - 5, 5)
        ),
    )  # fmt: skip

    assert edit_bytes(build_edit(spec)) < TWENTY_LIMIT
