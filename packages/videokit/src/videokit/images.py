"""A logo read once, cut to its drawing, and described by its colours."""

import io
import math
from pathlib import Path
from typing import Final

import resvg_py
from PIL import Image, ImageChops, ImageDraw, UnidentifiedImageError

from videokit.errors import VideoError

LOGO_SIDE: Final = 512
BADGE_PADDING: Final = 0.22
BADGE_MARGIN: Final = 0.07
SVG_FONT: Final = Path(__file__).parent / "fonts" / "svg" / "Inter-Regular.ttf"
SVG_FONT_FAMILY: Final = "Inter"
SVG_DRAW_SIDE: Final = 1024
ALPHA_FLOOR: Final = 16
PLAIN_TOLERANCE: Final = 24
SAMPLE_SIDE: Final = 96
MIN_SHARE: Final = 0.03
PLAIN_EDGE: Final = 0.97
BACKGROUND_TOLERANCE: Final = 40
SAME_COLOUR: Final = 48


class ImageReadError(VideoError):
    """The file is not a picture this module can read."""


def read_logo(data: bytes, *, svg: bool) -> Image.Image:
    """The file as an RGBA picture. ``ImageReadError`` if unreadable."""
    try:
        if svg:
            return _draw_svg(data.decode("utf-8"))
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            return opened.convert("RGBA")
    except (ValueError, OSError, UnidentifiedImageError, UnicodeDecodeError) as exc:
        raise ImageReadError(str(exc)) from exc


def _draw_svg(markup: str) -> Image.Image:
    first = _png_to_image(_svg_png(markup))
    side = max(first.size)
    if side >= SVG_DRAW_SIDE or side == 0:
        return first
    return _png_to_image(_svg_png(markup, zoom=SVG_DRAW_SIDE / side))


def _svg_png(markup: str, *, zoom: float | None = None) -> bytes:
    """Text in an SVG is drawn in a font the machine has; one it does not
    have - or a generic name like sans-serif, which resvg reads as Arial -
    falls back to the Inter shipped here, so the letters are not lost on a
    server with no such font."""
    return resvg_py.svg_to_bytes(
        svg_string=markup,
        zoom=zoom,
        font_files=[str(SVG_FONT)],
        font_family=SVG_FONT_FAMILY,
        sans_serif_family=SVG_FONT_FAMILY,
        serif_family=SVG_FONT_FAMILY,
    )


def _png_to_image(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as opened:
        opened.load()
        return opened.convert("RGBA")


def has_alpha(image: Image.Image) -> bool:
    """Whether any pixel lets the background through."""
    low = image.getchannel("A").getextrema()[0]
    return isinstance(low, int | float) and low < 255 - ALPHA_FLOOR


def trim(image: Image.Image) -> Image.Image:
    """The picture without its empty margin; as it is if nothing is drawn."""
    if has_alpha(image):
        mask = image.getchannel("A").point(lambda a: 255 if a >= ALPHA_FLOOR else 0)
    else:
        corner = image.getpixel((0, 0))
        flat = Image.new("RGBA", image.size, corner)
        difference = ImageChops.difference(image, flat).convert("L")
        mask = difference.point(lambda d: 255 if d > PLAIN_TOLERANCE else 0)
    box = mask.getbbox()
    return image.crop(box) if box else image


def plain_background(image: Image.Image) -> str:
    """The colour the picture sits on, as ``#rrggbb``: empty when it has
    transparency or its edge is not one colour."""
    if has_alpha(image):
        return ""
    edge = _edge(image.convert("RGB"))
    corner = edge[0]
    near = sum(1 for pixel in edge if _within(pixel, corner, PLAIN_TOLERANCE))
    if near < len(edge) * PLAIN_EDGE:
        return ""
    return "#{:02x}{:02x}{:02x}".format(*corner)


def remove_background(image: Image.Image, color: str) -> Image.Image:
    """The picture with ``color`` let through wherever it touches the edge."""
    cleared = image.convert("RGBA")
    width, height = cleared.size
    target = (*_rgb(color), 255)
    for x, y in _edge_points(width, height):
        pixel = cleared.getpixel((x, y))
        if isinstance(pixel, tuple) and pixel[3] and _close(pixel, target):
            ImageDraw.floodfill(
                cleared, (x, y), (0, 0, 0, 0), thresh=BACKGROUND_TOLERANCE
            )
    return cleared


def fit(image: Image.Image, side: int = LOGO_SIDE) -> Image.Image:
    """The picture inside ``side`` x ``side``, proportions kept, never enlarged."""
    fitted = image.copy()
    fitted.thumbnail((side, side), Image.Resampling.LANCZOS)
    return fitted


def silhouette(image: Image.Image, color: str) -> Image.Image:
    """The picture's shape, every pixel ``color`` (``#rrggbb``), alpha kept."""
    painted = Image.new("RGBA", image.size, _rgb(color))
    painted.putalpha(image.getchannel("A"))
    return painted


def badge(image: Image.Image, color: str) -> Image.Image:
    """The picture as it is, on a rounded plate of ``color`` around it."""
    width, height = image.size
    short = min(width, height)
    pad = round(short * BADGE_PADDING)
    radius = (short + 2 * pad) / 2
    inside = radius - BADGE_MARGIN * 2 * radius
    clear = radius - math.sqrt(max(inside**2 - (radius - pad) ** 2, 0.0))
    side = math.ceil(max(clear, pad))
    pad_x, pad_y = (side, pad) if width >= height else (pad, side)
    size = (width + 2 * pad_x, height + 2 * pad_y)
    plate = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1),
        radius=min(size) // 2,
        fill=(*_rgb(color), 255),
    )
    plate.alpha_composite(image.convert("RGBA"), (pad_x, pad_y))
    return plate


def palette(image: Image.Image, count: int = 5) -> tuple[str, ...]:
    """The main colours of what is drawn, commonest first, as ``#rrggbb``."""
    return tuple(colour for colour, _share in palette_shares(image, count))


def palette_shares(image: Image.Image, count: int = 5) -> tuple[tuple[str, float], ...]:
    """The main colours of what is drawn and the share of it each covers,
    commonest first. Colours under :data:`MIN_SHARE` are left out, near
    twins counted as one."""
    drawn = _drawn_pixels(image)
    if not drawn:
        return ()
    strip = Image.new("RGB", (len(drawn), 1))
    strip.putdata(drawn)
    quantized = strip.quantize(
        colors=count, method=Image.Quantize.MEDIANCUT, kmeans=count
    )
    colours = quantized.getpalette() or []
    found: list[tuple[tuple[int, int, int], int]] = []
    for pixels, index in sorted(quantized.getcolors() or [], reverse=True):
        at = int(index) * 3  # type: ignore[call-overload]  # a palette index
        rgb = (colours[at], colours[at + 1], colours[at + 2])
        twin = next(
            (i for i, (seen, _n) in enumerate(found) if _twins(rgb, seen)), None
        )
        if twin is None:
            found.append((rgb, pixels))
        else:
            found[twin] = (found[twin][0], found[twin][1] + pixels)
    return tuple(
        (f"#{r:02x}{g:02x}{b:02x}", round(n / len(drawn), 3))
        for (r, g, b), n in found
        if n / len(drawn) >= MIN_SHARE
    )


def _twins(first: tuple[int, int, int], second: tuple[int, int, int]) -> bool:
    return sum(abs(a - b) for a, b in zip(first, second, strict=True)) < SAME_COLOUR


def ink(image: Image.Image) -> str:
    """The average colour of what is drawn; empty when nothing is."""
    drawn = _drawn_pixels(image)
    if not drawn:
        return ""
    red, green, blue = (round(sum(p[i] for p in drawn) / len(drawn)) for i in range(3))
    return f"#{red:02x}{green:02x}{blue:02x}"


def png(image: Image.Image) -> bytes:
    """The picture as an optimised PNG."""
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _drawn_pixels(image: Image.Image) -> list[tuple[int, int, int]]:
    small = fit(image, SAMPLE_SIDE)
    pixels: list[tuple[int, int, int, int]] = list(small.get_flattened_data())  # type: ignore[arg-type]
    return [(r, g, b) for r, g, b, a in pixels if a >= 128]


def _edge(image: Image.Image) -> list[tuple[int, int, int]]:
    width, height = image.size
    return [image.getpixel(p) for p in _edge_points(width, height)]  # type: ignore[misc]


def _edge_points(width: int, height: int) -> list[tuple[int, int]]:
    """Every few pixels round the border, corners first."""
    step = max(1, max(width, height) // 128)
    corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    across = [(x, y) for x in range(0, width, step) for y in (0, height - 1)]
    down = [(x, y) for y in range(0, height, step) for x in (0, width - 1)]
    return corners + across + down


def _close(pixel: tuple[int, ...], target: tuple[int, ...]) -> bool:
    return _within(pixel, target, BACKGROUND_TOLERANCE)


def _within(pixel: tuple[int, ...], target: tuple[int, ...], tolerance: int) -> bool:
    """Every colour channel within ``tolerance`` of the target's."""
    return max(abs(a - b) for a, b in zip(pixel[:3], target[:3], strict=True)) <= (
        tolerance
    )


def _rgb(color: str) -> tuple[int, int, int]:
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
