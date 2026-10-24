"""Every font preset writes Uzbek in both scripts, and stays small; a clip
carries only the letters it writes."""

import base64
import io
import re

import pytest
from fontTools.ttLib import TTFont
from videokit import Brand
from videokit.components import component, component_clip, preview_page
from videokit.typefaces import FONT_PRESETS, FontPreset, font_css, font_file

# The Uzbek okina (U+02BB, as in o-okina, g-okina) and apostrophe
# (U+02BC), the curly quotes people type instead, guillemets, the dash and
# the numero sign - then Russian Cyrillic and the four Uzbek Cyrillic
# letters Russian lacks. Written as escapes: the okina and the curly
# quotes look like other characters in an editor.
UZBEK = "\u02bb\u02bc\u2018\u2019"
CYRILLIC = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
UZBEK_CYRILLIC = "ЎўҚқҒғҲҳ"
# What prices, offers and contacts are written with: guillemets, the en and
# em dash, curly double quotes, the numero sign, money and arithmetic signs,
# and every digit.
SIGNS = "\u00ab\u00bb\u2013\u2014\u201c\u201d\u2116$%+-=@#&*/:;!?.,()0123456789"
# Shotstack refuses an edit over 390 KB and every clip carries its font.
MAX_FONT_BYTES = 20 * 1024


@pytest.mark.parametrize("preset", FONT_PRESETS)
def test_a_preset_has_every_letter_a_montage_writes(preset: FontPreset) -> None:
    letters = TTFont(font_file(preset)).getBestCmap()

    missing = [
        ch for ch in UZBEK + CYRILLIC + UZBEK_CYRILLIC + SIGNS if ord(ch) not in letters
    ]

    assert missing == []


@pytest.mark.parametrize("preset", FONT_PRESETS)
def test_a_preset_is_small_and_inlined_once(preset: FontPreset) -> None:
    assert font_file(preset).stat().st_size <= MAX_FONT_BYTES
    assert font_css(preset) is font_css(preset)
    assert "font/woff2;base64," in font_css(preset)


def _carried(css: str) -> TTFont:
    found = re.search(r"base64,([A-Za-z0-9+/=]+)", css)
    assert found is not None
    return TTFont(io.BytesIO(base64.b64decode(found.group(1))))


def test_the_brands_preset_is_the_one_its_clips_carry() -> None:
    page = preview_page(
        component("end_card"), props={}, brand=Brand(name="Bahor", font="elegant"),
        zone="FULL",
    )  # fmt: skip

    assert _carried(page)["name"].getDebugName(1) == "Noto Serif"


WORD = "Bo\u02bbyab \u049a"


def test_a_cut_copy_keeps_the_letters_asked_for_and_no_others() -> None:
    letters = set(_carried(font_css("modern", letters=WORD)).getBestCmap())

    assert {ord(ch) for ch in WORD} <= letters
    assert not {ord(ch) for ch in "bOqz"} & (letters - {ord("b")})


def test_a_clip_carries_its_own_letters_and_a_tenth_of_the_file() -> None:
    clip = component_clip(
        component("chips_list"),
        props={"title": "Nega biz?", "items": ["Tez yetkazish", "Kafolat bor"]},
        brand=Brand(name="Bahor"),
        zone="TOP_PANEL",
        start=0,
        length=4,
        resolution="1080",
        aspect_ratio="9:16",
    )["asset"]
    carried = _carried(clip["css"])

    assert {ord(ch) for ch in "NegabizTKfoltyshkr?"} <= set(carried.getBestCmap())
    assert len(font_css("modern", letters=clip["html"])) < len(font_css("modern")) / 3


def test_a_preview_shows_the_settled_frame_without_gsap() -> None:
    page = preview_page(
        component("lower_third"), props={}, brand=Brand(name="Bahor"),
        zone="LOWER_THIRD",
    )  # fmt: skip

    assert page.startswith("<!doctype html>")
    assert "window.gsap=" in page
    assert ">Bahor<" in page
    # The stand-in comes first: the component's own timeline calls it.
    assert page.index("window.gsap=") < page.index("gsap.timeline()")
