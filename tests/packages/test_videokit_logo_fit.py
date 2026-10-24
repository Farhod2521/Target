"""videokit: how big a logo is drawn for its lettering to read, and whether
it sits whole on its plate."""

import base64
import io

from PIL import Image, ImageDraw, ImageFont
from videokit import Brand, ComponentUse, Cut, EditSpec, build_edit
from videokit.images import badge
from videokit.logo_fit import (
    MIN_TEXT_PX,
    corner_size,
    logo_copy,
    name_bar_logo,
)
from videokit.preflight import preflight

FONT = "packages/videokit/src/videokit/fonts/svg/Inter-Regular.ttf"


def _osh(size: int = 76) -> Image.Image:
    """The test brand's logo: a bowl and OSH MARKAZI beside it."""
    image = Image.new("RGBA", (1000, 500), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.pieslice((120, 120, 380, 380), 0, 180, fill=(180, 83, 9, 255))
    draw.rectangle((110, 240, 390, 255), fill=(120, 53, 15, 255))
    draw.text((420, 190), "OSH MARKAZI", font=ImageFont.truetype(FONT, size),
              fill=(41, 37, 36, 255))  # fmt: skip
    return image.crop(image.getbbox())


def _uri(image: Image.Image, width: int = 256) -> str:
    small = image.resize((width, round(image.height * width / image.width)))
    out = io.BytesIO()
    small.save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def _old_badge(image: Image.Image) -> Image.Image:
    """A plate as tight as the one the stage render showed cutting the bowl."""
    width, height = image.size
    pad = round(min(width, height) * 0.08)
    plate = Image.new("RGBA", (width + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        (0, 0, plate.width - 1, plate.height - 1),
        radius=plate.height // 2,
        fill=(255, 255, 255, 255),
    )
    plate.alpha_composite(image, (pad, pad))
    return plate


def test_the_lettering_is_found_and_measured() -> None:
    copy = logo_copy(_uri(_osh()))

    assert copy is not None and copy.text_share is not None
    # The capitals are about a third of a logo this shape.
    assert 0.2 < copy.text_share < 0.45


def test_a_mark_with_no_letters_has_no_lettering() -> None:
    image = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((10, 10, 290, 290), fill=(200, 30, 60, 255))

    copy = logo_copy(_uri(image))

    assert copy is not None and copy.text_share is None and copy.needed_height() == 0


def test_a_plate_that_cuts_into_the_mark_is_caught_and_the_new_one_is_not() -> None:
    tight = logo_copy(_uri(_old_badge(_osh().resize((256, 53)))))
    made = logo_copy(_uri(badge(_osh().resize((256, 53)), "#ffffff"), width=294))

    assert tight is not None and not tight.on_plate_whole
    assert made is not None and made.on_plate_whole


def test_the_corner_grows_until_the_name_reads_or_goes_without() -> None:
    plain = _uri(badge(_osh().resize((256, 53)), "#ffffff"))
    copy = logo_copy(plain)
    size = corner_size(plain)

    assert copy is not None and size is not None
    assert copy.text_px(size[1]) >= MIN_TEXT_PX  # type: ignore[operator]
    # Small lettering on a wide logo cannot read in a corner at all.
    small = _uri(badge(_osh(size=30).resize((400, 53)), "#ffffff"), width=400)
    assert corner_size(small) is None


def test_the_name_bar_writes_the_name_when_the_logo_cannot_say_it() -> None:
    readable = _uri(_osh())
    tiny = _uri(_osh(size=24), width=400)

    assert name_bar_logo(readable) is not None
    assert name_bar_logo(tiny) is None


def test_a_cut_logo_stops_the_render() -> None:
    cut = _uri(_old_badge(_osh().resize((256, 53))))
    brand = Brand(name="Osh Markazi", cta_text="Yozing", logo=cut, logo_on_dark=cut)
    spec = EditSpec(
        source_url="https://example.test/v.mp4",
        cuts=(Cut(start=0, end=10),),
        resolution="1080",
        brand=brand,
        components=(
            ComponentUse(name="hook_title", zone="TOP_TITLE", start=0, length=2,
                         props={"text": "Osh tayyor"}),
            ComponentUse(name="end_card", zone="FULL", start=7, length=3),
            ComponentUse(name="end_cta", zone="FULL", start=7.3, length=2.7),
        ),
    )  # fmt: skip

    kinds = [p.kind for p in preflight(spec, build_edit(spec))]

    assert "logo_cut" in kinds
