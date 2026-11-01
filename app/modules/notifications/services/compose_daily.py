"""The daily and weekly report's first message, as somebody reads it on a phone.

What the period cost altogether, and a button under it for every pair that
spent, with that pair's money on it. A press replaces the message in place with
that pair's figures - see
:mod:`app.modules.notifications.services.compose_day_pair`.

Figures only. Nothing here judges a day: no verdict, no warning, no reading
by a model. Somebody who wants to know whether a figure is good asks the
assistant, which reads the same figures.

Built by :mod:`app.modules.notifications.services.compose`'s rules: HTML, and
every value escaped before it meets a tag.
"""

from typing import Final

from telegramkit import Button

from app.modules.notifications.keys import daily_pair_data, weekly_pair_data
from app.modules.notifications.services.compose import (
    Message,
    _bold,
    _italic,
    escaped,
    miniapp_button,
)
from core.chat.day_report import DailyReport, DayBook

SEPARATOR: Final = " · "
# The longest a button may run: a phone draws it one line high and clips the
# rest, which is why the money goes first and the name is what is cut.
BUTTON_CHARS: Final = 40
# Telegram takes a hundred buttons under one message.
MAX_PAIR_BUTTONS: Final = 90
MAX_QUIET_NAMES: Final = 5


def list_message(*, book: DayBook) -> Message:
    """The day's total. The buttons under it carry each pair's share."""
    lines = [_bold(heading(book))]
    if book.totals:
        lines.append(f"{escaped('Jami sarflandi')}: {_totals(book)}")
    if status := status_line(book):
        lines.append(status)
    lines += closing_lines(book)
    return Message(text="\n".join(lines))


def list_buttons(*, book: DayBook) -> tuple[Button, ...]:
    """A button for each pair that spent, and the cabinet."""
    return (
        *(
            Button(
                text=_button_title(report),
                data=pair_press(book, report),
                row="own",
            )
            for report in book.spent[:MAX_PAIR_BUTTONS]
        ),
        *miniapp_button(route="metrics:dashboard", label="Kabinetda ochish"),
    )


def pair_press(book: DayBook, report: DailyReport) -> str:
    if book.weekly:
        return weekly_pair_data(since=book.day, pair=report.pair)
    return daily_pair_data(day=book.day, pair=report.pair)


def heading(book: DayBook) -> str:
    if book.weekly:
        name = "Haftalik hisobot"
    else:
        name = "Bugun" if book.ongoing else "Kunlik hisobot"
    return f"{name}{SEPARATOR}{book.day_text}"


def status_line(book: DayBook) -> str:
    """Whether these figures are the day's own, or empty when they are.

    Said before anything else about the day: somebody who reads two lines
    and puts the phone down should not act on an afternoon's figures
    believing they are the day's.
    """
    if book.ongoing:
        return _italic("Kun hali tugamagan — raqamlar shu paytgacha.")
    if not book.final:
        return _italic("Raqamlar hali yakuniy emas — kun to'liq o'qilmagan.")
    return ""


def closing_lines(book: DayBook) -> list[str]:
    """The day's last lines, under the total or under a lone pair's figures."""
    lines = []
    if book.quiet:
        lines += ["", _quiet_line(book.quiet)]
    if book.outside:
        money = SEPARATOR.join(book.outside)
        lines += [
            "",
            _italic(f"Tanlanmagan sahifalar: yana {money} (jamiga kirmaydi)"),
        ]
    return lines


def _quiet_line(reports: tuple[DailyReport, ...]) -> str:
    names = ", ".join(report.title for report in reports[:MAX_QUIET_NAMES])
    left = len(reports) - MAX_QUIET_NAMES
    tail = f" va yana {left} ta" if left > 0 else ""
    return _italic(f"Sarf bo'lmagan: {names}{tail}")


def _totals(book: DayBook) -> str:
    return escaped(SEPARATOR).join(
        _bold(total.spend) + compared(book, total.before) for total in book.totals
    )


def compared(book: DayBook, before: str) -> str:
    word = "oldingi hafta" if book.weekly else "oldingi kun"
    return escaped(f" ({word} {before})") if before else ""


def _button_title(report: DailyReport) -> str:
    money = report.spend if report.spend_minor > 0 else report.other_currency[0]
    title = f"{money}{SEPARATOR}{report.title}"
    if len(title) <= BUTTON_CHARS:
        return title
    return title[: BUTTON_CHARS - 1].rstrip() + "…"


__all__ = [
    "SEPARATOR",
    "closing_lines",
    "compared",
    "heading",
    "list_buttons",
    "list_message",
    "pair_press",
    "status_line",
]
