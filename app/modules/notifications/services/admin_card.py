"""The owners' figures drawn onto the card picture.

``assets/admin_card.png`` is the designed card with its icons and panels but
no words; this writes the figures into it, each at the place the design
left for it, and hands back a JPEG for ``sendPhoto``. A value wider than its
place is set smaller, then cut with an ellipsis, so nothing runs into the
next panel. Fonts are the Inter faces videokit already ships: they carry
Latin, Cyrillic and the Uzbek okina.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Final

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from app.modules.notifications.services.admin_stats import Stats

TEMPLATE: Final = Path(__file__).resolve().parent.parent / "assets" / "admin_card.png"
INK: Final = (27, 37, 64)
MUTED: Final = (96, 108, 135)
LINE: Final = (196, 206, 228)

# The three period panels: where each one's words start, and how wide they may run.
COLUMNS: Final = (114, 496, 878)
COLUMN_WIDTH: Final = 268
HEADER_Y: Final = 205
ROWS_Y: Final = (263, 305, 345, 409, 451, 493, 535, 578)
SUBLINE_Y: Final = 369

SIGNUP_ROWS_Y: Final = (903, 955, 1007, 1058, 1110, 1162, 1214)
SIGNUPS_ON_CARD: Final = len(SIGNUP_ROWS_Y)

Font = ImageFont.FreeTypeFont


@cache
def _font(bold: bool, size: int) -> Font:
    from importlib.resources import files

    name = "fonts/modern/font.woff2" if bold else "fonts/svg/Inter-Regular.ttf"
    with (files("videokit") / name).open("rb") as handle:
        return ImageFont.truetype(BytesIO(handle.read()), size)


@dataclass
class Pen:
    draw: ImageDraw.ImageDraw

    def width(self, text: str, font: Font) -> float:
        return self.draw.textlength(text, font=font)

    def fitted(
        self, text: str, *, bold: bool, size: int, room: float
    ) -> tuple[str, Font]:
        """Smaller until it fits, down to two thirds; then cut with an ellipsis."""
        smallest = max(10, size * 2 // 3)
        for step in range(size, smallest - 1, -1):
            font = _font(bold, step)
            if self.width(text, font) <= room:
                return text, font
        font = _font(bold, smallest)
        while text and self.width(text + "…", font) > room:
            text = text[:-1]
        return text.rstrip() + "…", font

    def write(
        self,
        x: float,
        y: float,
        text: str,
        *,
        bold: bool = False,
        size: int = 20,
        room: float = 10_000,
        colour: tuple[int, int, int] = INK,
    ) -> float:
        """Text with its left edge at x and its middle at y; returns where it ended."""
        text, font = self.fitted(text, bold=bold, size=size, room=room)
        self.draw.text((x, y), text, font=font, fill=colour, anchor="lm")
        return x + self.width(text, font)

    def pair(
        self, x: float, y: float, label: str, value: str, *, size: int, room: float
    ) -> float:
        """``Label: value`` with the value in bold, the two fitted together."""
        for step in range(size, max(10, size * 2 // 3) - 1, -1):
            left, right = _font(False, step), _font(True, step)
            if self.width(f"{label}: ", left) + self.width(value, right) <= room:
                end = self.write(x, y, f"{label}: ", size=step)
                return self.write(end, y, value, bold=True, size=step)
        end = self.write(x, y, f"{label}: ", size=max(10, size * 2 // 3))
        return self.write(
            end, y, value, bold=True, size=max(10, size * 2 // 3), room=room - (end - x)
        )


def _run(
    pen: Pen, x: float, y: float, parts: Sequence[tuple[str, str]], size: int
) -> None:
    """Several ``Label: value`` on one line, divided by thin bars."""
    for index, (label, value) in enumerate(parts):
        if index:
            pen.draw.line((x + 8, y - 11, x + 8, y + 11), fill=LINE, width=2)
            x += 20
        x = pen.pair(x, y, label, value, size=size, room=400) + 4


def draw_card(stats: "Stats") -> bytes:
    """The card as JPEG bytes, ready for sendPhoto."""
    image = Image.open(TEMPLATE).convert("RGB")
    pen = Pen(ImageDraw.Draw(image))

    pen.write(172, 55, "Admin statistika", bold=True, size=46)
    pen.write(226, 107, stats.stamp, size=28, colour=MUTED)

    for x, period in zip(COLUMNS, stats.periods, strict=False):
        pen.write(x - 4, HEADER_Y, period.label, bold=True, size=26)
        conversion = "—" if period.conversion is None else f"{period.conversion}%"
        rows = (
            ("Ro'yxatdan o'tdi", str(period.signups)),
            ("Obuna to'ladi", str(period.payers)),
            ("Tushum", period.amount),
            ("Konversiya", conversion),
            ("Kampaniya", f"{period.launched} (xato {period.failed})"),
            ("Lid", str(period.leads)),
            ("Reklama sarfi", period.spend),
            ("AI", period.ai_cost),
        )
        for y, (label, value) in zip(ROWS_Y, rows, strict=True):
            pen.pair(x, y, label.replace("'", "ʻ"), value, size=21, room=COLUMN_WIDTH)
        pen.write(x, SUBLINE_Y, f"({period.payments} ta toʻlov)", size=17, colour=MUTED)

    pen.write(138, 687, "Mijozlar", bold=True, size=26)
    end = pen.write(138, 731, "Jami:", size=24)
    pen.write(end + 14, 731, str(stats.total), bold=True, size=34, room=170)
    for x, top, bottom in (
        (417, ("Faol obuna", stats.paying), ("Sinov", stats.trial)),
        (680, ("Muddati tugaydi", stats.expiring), ("Ketgan", stats.churned)),
        (
            957,
            ("Sozlamagan", stats.setup_unfinished),
            ("Meta ulanmagan", stats.meta_missing),
        ),
    ):
        pen.pair(x, 691, top[0], str(top[1]), size=19, room=185)
        pen.pair(x, 735, bottom[0], str(bottom[1]), size=19, room=185)

    pen.write(114, 840, "Ofisni kutmoqda", bold=True, size=23)
    pen.pair(52, 897, "Javobsiz chat", str(stats.support), size=18, room=150)
    pen.pair(222, 897, "Promo", str(stats.promos), size=18, room=80)
    pen.draw.line((312, 886, 312, 908), fill=LINE, width=2)
    pen.pair(326, 897, "Toʻlanmagan", str(stats.unpaid), size=18, room=140)
    pen.pair(52, 937, "Ushlangan", str(stats.holds), size=18, room=150)
    pen.pair(222, 937, "Blok", str(stats.blocks), size=18, room=80)

    pen.write(596, 840, "Oxirgi roʻyxatdan oʻtganlar", bold=True, size=23)
    for y, row in zip(SIGNUP_ROWS_Y, stats.signups, strict=False):
        pen.write(560, y, row.when, size=16)
        pen.write(722, y - 12, row.name, bold=True, size=17, room=290)
        pen.write(751, y + 11, row.email, size=14, room=236 if row.phone else 400)
        if row.phone:
            pen.write(1025, y + 11, row.phone, size=14, room=130)

    out = BytesIO()
    image.save(out, format="JPEG", quality=90, optimize=True)
    return out.getvalue()


__all__ = ["SIGNUPS_ON_CARD", "draw_card"]
