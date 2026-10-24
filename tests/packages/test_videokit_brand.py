"""videokit: a montage drawn in its brand - colours, font, logo, contacts."""

import io
import re

import pytest
from PIL import Image
from videokit import Brand
from videokit.brightness import corner_brightness
from videokit.colors import BLACK, TEXT_CONTRAST, contrast_ratio
from videokit.components import component, component_clip, font_css
from videokit.karaoke import caption_colors, karaoke
from videokit.models import CaptionLine, CaptionWord

DARK_COPY = "data:image/png;base64,REFSSw=="
LIGHT_COPY = "data:image/png;base64,TElHSFQ="
OWN = "data:image/png;base64,T1dO"


def _clip(name: str, brand: Brand, **props: str) -> dict[str, str]:
    item = component(name)
    return component_clip(
        item,
        props=props or item.example,
        brand=brand,
        zone=item.zones[0],
        start=0,
        length=3,
        resolution="1080",
        aspect_ratio="9:16",
    )["asset"]


# --- Subtitles -------------------------------------------------------------


@pytest.mark.parametrize(
    ("accent", "lit"),
    [
        ("#f0509b", "#f0509b"),  # reads on the outline: used as it is
        ("#22c55e", "#22c55e"),
        ("#0f172a", None),  # navy: too dark for the outline, lightened
        ("#fafafa", None),  # near white: too close to the words
    ],
)
def test_the_lit_word_is_the_accent_where_it_reads(
    accent: str, lit: str | None
) -> None:
    ink, chosen = caption_colors(Brand(accent=accent, primary="#5b1a8c"))

    assert ink == "#ffffff"
    if lit is not None:
        assert chosen == lit
    else:
        assert chosen != accent
    assert contrast_ratio(chosen, BLACK) >= TEXT_CONTRAST
    assert contrast_ratio(chosen, ink) >= 1.3


def test_dark_brand_text_is_not_used_on_the_black_outline() -> None:
    ink, _ = caption_colors(Brand(text="#111111"))

    assert ink == "#ffffff"


def test_subtitles_are_drawn_in_the_brand_font_and_colours() -> None:
    brand = Brand(accent="#22c55e", font="elegant")
    line = CaptionLine(
        start=1.0, end=2.0, words=(CaptionWord(text="Salom", start=1.0, end=2.0),)
    )

    asset = karaoke([(line, 2.1)], brand=brand, font_px=68, stroke_px=10)

    assert font_css("elegant", letters="Salom") in asset["css"]
    assert "color:'#22c55e'" in asset["js"]
    assert "#ffd400" not in asset["js"] + asset["css"]


# --- Components --------------------------------------------------------------


def test_the_name_bar_leaves_out_a_name_the_logo_already_spells() -> None:
    spelled = Brand(name="Osh Markazi", logo=OWN, name_in_logo=True)
    partial = Brand(name="Chilonzor Fitnes", logo=OWN, name_in_logo=False)

    alone = _clip("lower_third", spelled)["html"]
    beside = _clip("lower_third", partial)["html"]

    assert "Osh Markazi" not in alone and 'class="solo"' in alone
    assert "Chilonzor Fitnes" in beside and 'class="mark"' in beside


def test_a_name_without_a_logo_is_always_written() -> None:
    html = _clip("lower_third", Brand(name="Bahor", name_in_logo=True))["html"]

    assert "Bahor" in html and 'class="ini"' in html


def test_the_button_carries_the_handle_and_the_phone_together() -> None:
    brand = Brand(cta_text="Yozing", cta_handle="@bahor", cta_phone="+12025550123")

    html = _clip("cta_button", brand)["html"]

    assert '<span class="l1 own">Yozing</span>' in html
    assert '<span class="l2">@bahor · +12025550123</span>' in html
    assert brand.cta_label == "Yozing: @bahor · +12025550123"


@pytest.mark.parametrize("name", ["end_card", "lower_third", "chips_list"])
def test_brand_surfaces_take_every_colour_from_the_brand(name: str) -> None:
    css = _clip(name, Brand(primary="#16a34a", logo=OWN))["css"]
    own = css.split("}", 2)[-1]  # after the font and the base rules

    assert not re.search(r"#060a1c|#0b1020|background:#ffffff", own)
    assert "--primary-deep:#" in css and "--on-primary:#" in css


def test_logos_on_the_brand_colour_are_the_copy_made_for_it() -> None:
    dark = Brand(primary="#1e293b", logo=OWN, logo_on_dark=DARK_COPY)
    light = Brand(primary="#fde68a", logo=OWN, logo_on_light=LIGHT_COPY)

    assert DARK_COPY in _clip("end_card", dark)["html"]
    assert LIGHT_COPY in _clip("end_card", light)["html"]
    assert dark.logo_on("#ffffff") == OWN  # no light copy: its own


def test_the_corner_logo_is_small_see_through_and_carries_no_font() -> None:
    brand = Brand(logo=OWN, logo_on_dark=DARK_COPY, logo_on_light=LIGHT_COPY)

    on_dark = _clip("corner_logo", brand, on_dark="1")
    on_light = _clip("corner_logo", brand, on_light="1")

    assert DARK_COPY in on_dark["html"] and LIGHT_COPY not in on_dark["html"]
    assert LIGHT_COPY in on_light["html"]
    assert "@font-face" not in on_dark["css"]
    assert "height:110px" in on_dark["css"] and "opacity:.85" in on_dark["css"]


# --- The light behind the corner ---------------------------------------------


def _still(size: tuple[int, int], corner: tuple[int, int, int, int]) -> bytes:
    """Black, with a white block where ``corner`` (in pixels) is."""
    picture = Image.new("RGB", size, (0, 0, 0))
    picture.paste((255, 255, 255), corner)
    out = io.BytesIO()
    picture.save(out, format="JPEG", quality=95)
    return out.getvalue()


def test_the_corner_is_read_where_the_logo_sits() -> None:
    upright = _still((360, 640), (16, 78, 89, 115))
    elsewhere = _still((360, 640), (0, 500, 100, 640))

    assert corner_brightness(upright) > 0.9  # type: ignore[operator]
    assert corner_brightness(elsewhere) < 0.1  # type: ignore[operator]


def test_a_wide_still_is_read_where_the_upright_frame_crops_it() -> None:
    """A 16:9 still shows only its middle in a 9:16 frame; the logo's
    corner is the top left of that middle, not of the still."""
    # 640x360: the frame shows x 218-421; its top left corner is ~ x 227-268.
    wide = _still((640, 360), (227, 44, 268, 65))

    assert corner_brightness(wide) > 0.8  # type: ignore[operator]
    assert corner_brightness(b"not a picture") is None


def test_a_corner_half_sky_half_dark_reads_as_light() -> None:
    """The stage render that showed it: a white logo over a car mirror and
    the sky above it. The mean called it dark; the sky is what it is lost on."""
    picture = Image.new("RGB", (360, 640), (20, 20, 20))
    picture.paste((200, 220, 240), (16, 78, 89, 96))  # the sky, top of the box
    out = io.BytesIO()
    picture.save(out, format="JPEG", quality=95)

    assert corner_brightness(out.getvalue()) > 0.5  # type: ignore[operator]


def test_a_line_is_centred_by_gsap_so_its_rise_cannot_undo_it() -> None:
    """The line's rise tweens y; a CSS translate would be overwritten by it
    and a line on two rows would hang half its height below its band."""
    line = CaptionLine(
        start=1.0, end=2.0, words=(CaptionWord(text="Salom", start=1.0, end=2.0),)
    )

    asset = karaoke([(line, 2.1)], brand=Brand(), font_px=68, stroke_px=10)

    assert "translate" not in asset["css"]
    assert asset["js"].startswith("gsap.set('.l',{yPercent:-50})")
