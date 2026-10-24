"""videokit.images: a logo read, cut to its drawing, painted, described."""

import io

import pytest
from PIL import Image, ImageDraw
from videokit.images import (
    ImageReadError,
    fit,
    has_alpha,
    ink,
    palette,
    plain_background,
    png,
    read_logo,
    remove_background,
    silhouette,
    trim,
)


def _png(picture: Image.Image) -> bytes:
    out = io.BytesIO()
    picture.save(out, format="PNG")
    return out.getvalue()


def _two_colours() -> Image.Image:
    picture = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(picture)
    draw.rectangle((100, 80, 299, 219), fill=(220, 30, 60, 255))
    draw.rectangle((100, 80, 159, 139), fill=(20, 40, 200, 255))
    return picture


def test_a_transparent_margin_is_cut_away() -> None:
    picture = read_logo(_png(_two_colours()), svg=False)

    assert has_alpha(picture)
    assert trim(picture).size == (200, 140)


def test_a_plain_background_is_cut_away_from_a_picture_without_transparency() -> None:
    flat = Image.new("RGB", (300, 200), (255, 255, 255))
    ImageDraw.Draw(flat).rectangle((50, 50, 249, 149), fill=(0, 0, 0))
    out = io.BytesIO()
    flat.save(out, format="JPEG", quality=95)

    picture = read_logo(out.getvalue(), svg=False)

    assert not has_alpha(picture)
    width, height = trim(picture).size
    assert abs(width - 200) <= 2 and abs(height - 100) <= 2


def test_the_main_colours_come_commonest_first_and_near_twins_are_one() -> None:
    picture = trim(read_logo(_png(_two_colours()), svg=False))

    found = palette(picture)

    assert len(found) == 2
    assert found[0] == "#dc1e3c"
    assert ink(picture).startswith("#")


def test_a_silhouette_keeps_the_shape_and_paints_it() -> None:
    painted = silhouette(_two_colours(), "#ffffff")

    assert painted.getpixel((120, 100)) == (255, 255, 255, 255)
    assert painted.getpixel((5, 5))[3] == 0


def test_fitting_shrinks_and_never_enlarges() -> None:
    big = Image.new("RGBA", (2000, 1000))
    small = Image.new("RGBA", (100, 50))

    assert fit(big, 512).size == (512, 256)
    assert fit(small, 512).size == (100, 50)


def test_an_svg_is_drawn_big_enough_to_trim() -> None:
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
        b'<rect fill="#00aa77" x="10" y="10" width="80" height="30"/></svg>'
    )

    picture = read_logo(svg, svg=True)

    assert max(picture.size) == 1024
    assert palette(trim(picture)) == ("#00aa77",)
    assert png(fit(trim(picture))).startswith(b"\x89PNG")


@pytest.mark.parametrize(("data", "svg"), [(b"not a picture", False), (b"<svg", True)])
def test_a_file_that_is_not_a_picture_is_refused(data: bytes, svg: bool) -> None:
    with pytest.raises(ImageReadError):
        read_logo(data, svg=svg)


def _jpeg(picture: Image.Image) -> bytes:
    out = io.BytesIO()
    picture.convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue()


def _ring_on_white() -> Image.Image:
    """A black ring on white paper, white inside the ring too."""
    picture = Image.new("RGB", (300, 300), (255, 255, 255))
    ImageDraw.Draw(picture).ellipse((50, 50, 250, 250), outline=(0, 0, 0), width=30)
    return picture


def test_a_white_paper_ground_is_found_and_let_through_from_the_edge() -> None:
    picture = read_logo(_jpeg(_ring_on_white()), svg=False)

    ground = plain_background(picture)
    cleared = remove_background(picture, ground)

    assert all(int(ground[i : i + 2], 16) >= 240 for i in (1, 3, 5))
    assert cleared.getpixel((5, 5))[3] == 0
    # The white inside the ring does not touch the edge, so it stays.
    assert cleared.getpixel((150, 150))[3] == 255
    assert cleared.getpixel((150, 60))[:3] < (60, 60, 60)


def test_no_plain_ground_on_a_busy_edge_or_a_transparent_logo() -> None:
    stripes = Image.new("RGB", (200, 200))
    draw = ImageDraw.Draw(stripes)
    for x in range(0, 200, 20):
        draw.rectangle((x, 0, x + 9, 199), fill=(255, 0, 0))

    assert plain_background(stripes.convert("RGBA")) == ""
    assert plain_background(_two_colours()) == ""


@pytest.mark.parametrize("family", ["sans-serif", "No Such Font", "serif"])
def test_a_text_only_svg_is_drawn_even_without_its_font(family: str) -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 80">'
        f'<text x="10" y="55" font-size="48" font-family="{family}">'
        "O\u02bbzbek \u040e\u0437</text></svg>"
    ).encode()

    picture = trim(read_logo(svg, svg=True))

    assert ink(picture)
    assert picture.size[0] > picture.size[1] * 2


def test_a_badge_keeps_the_colours_on_a_rounded_plate() -> None:
    from videokit.images import badge

    plated = badge(_two_colours(), "#ffffff")
    width, height = plated.size
    pad = round(300 * 0.22)
    side = (width - 400) // 2

    assert height == 300 + 2 * pad and side > pad
    # The corners are rounded away; the plate's middle edge is white.
    assert plated.getpixel((0, 0))[3] == 0
    assert plated.getpixel((width // 2, 2)) == (255, 255, 255, 255)
    # The logo's own colours are where they were, moved in by the margin.
    assert plated.getpixel((side + 200, pad + 200)) == (220, 30, 60, 255)
    assert plated.getpixel((side + 120, pad + 100)) == (20, 40, 200, 255)


def test_a_wide_badge_keeps_the_logo_inside_its_rounded_ends() -> None:
    """The stage render that showed it: OSH MARKAZI, four times wider than
    tall, had its last letter cut by the pill's rounded end."""
    from videokit.images import badge

    # A see-through logo shows the plate alone where the logo would be.
    wide = Image.new("RGBA", (800, 200), (0, 0, 0, 0))

    plated = badge(wide, "#ffffff")
    width, height = plated.size
    side, pad = (width - 800) // 2, (height - 200) // 2

    # The plate reaches every corner of the logo: none is rounded off.
    for x, y in ((side, pad), (side + 799, pad), (side, pad + 199),
                 (side + 799, pad + 199)):  # fmt: skip
        assert plated.getpixel((x, y)) == (255, 255, 255, 255)
