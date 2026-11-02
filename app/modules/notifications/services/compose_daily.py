"""The daily and weekly report's first message, as somebody reads it on a phone.

What the period cost altogether, and a button under it for every pair that
spent, with that pair's money on it. A press replaces the message in place with
that pair's figures - see
:mod:`app.modules.notifications.services.compose_day_pair`.

**Sections with room around them.** A message is short blocks with a rule and
a blank line either side, figures in bold, so the eye finds the total and the
results without reading the words between them.

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
# Short enough not to wrap on a narrow phone, where a rule broken in two is
# worse than none.
RULE: Final = "──────────────"
# The longest a button may run: a phone draws it one line high and clips the
# rest, which is why the money goes first and the name is what is cut.
BUTTON_CHARS: Final = 40
# Telegram takes a hundred buttons under one message.
MAX_PAIR_BUTTONS: Final = 90
MAX_QUIET_NAMES: Final = 5


def sectioned(*sections: list[str]) -> str:
    """The sections that have anything in them, a rule between each two."""
    filled = ["\n".join(lines) for lines in sections if lines]
    return f"\n\n{RULE}\n\n".join(filled)


def list_message(*, book: DayBook) -> Message:
    """The period's total. The buttons under it carry each pair's share."""
    return Message(
        text=sectioned(
            [heading(book), escaped(book.day_text)],
            _total_section(book),
            *closing_sections(book),
            status_section(book),
        )
    )


def list_buttons(*, book: DayBook) -> tuple[Button, ...]:
    """A button for each pair that spent, and the cabinet."""
    return (
        *(
            Button(
                text=_button_title(book, report),
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
    return f"📊 {_bold(name.upper())}"


def status_section(book: DayBook) -> list[str]:
    """Whether these figures are the period's own, or nothing when they are."""
    if book.ongoing:
        return [_italic("⏳ Kun hali tugamagan — raqamlar shu paytgacha")]
    if not book.final:
        return [_italic("⏳ Raqamlar hali yakuniy emas")]
    return []


def closing_sections(book: DayBook) -> list[list[str]]:
    """What the period also says: the pairs that were quiet, and money that
    fell outside the subscription."""
    sections = []
    if book.quiet:
        sections.append([f"⏸ {_bold("Sarf bo'lmagan")}", *_quiet_names(book.quiet)])
    if book.outside:
        money = SEPARATOR.join(book.outside)
        sections.append(
            [
                f"📁 {_bold('Tanlanmagan sahifalar')}",
                f"Yana {_bold(money)} {escaped('(jamiga kirmaydi)')}",
            ]
        )
    return sections


def _total_section(book: DayBook) -> list[str]:
    lines: list[str] = []
    for total in book.totals:
        lines.append(f"💰 {_bold(f'Jami sarf: {total.spend}')}")
        if line := compared(book, total.before, total.change):
            lines.append(line)
    return lines


def compared(book: DayBook, before: str, change: str) -> str:
    """«Oldingi kun: $63,32 (+94%)», or nothing with nothing to compare."""
    if not before:
        return ""
    word = "Oldingi hafta" if book.weekly else "Oldingi kun"
    moved = f" ({change})" if change else ""
    return f"{escaped(word)}: {_bold(before)}{escaped(moved)}"


def _quiet_names(reports: tuple[DailyReport, ...]) -> list[str]:
    names = [escaped(f"• {report.title}") for report in reports[:MAX_QUIET_NAMES]]
    left = len(reports) - MAX_QUIET_NAMES
    return [*names, escaped(f"• Yana {left} ta")] if left > 0 else names


def _button_title(book: DayBook, report: DailyReport) -> str:
    """Money and the page. The account joins only to tell two pairs of one page
    apart: on a button it is what gets cut off."""
    money = report.spend if report.spend_minor > 0 else report.other_currency[0]
    pages = [item.page for item in book.reports].count(report.page)
    name = report.title if pages > 1 else report.page or report.title
    title = f"{money}{SEPARATOR}{name}"
    if len(title) <= BUTTON_CHARS:
        return title
    return title[: BUTTON_CHARS - 1].rstrip() + "…"


__all__ = [
    "RULE",
    "SEPARATOR",
    "closing_sections",
    "compared",
    "heading",
    "list_buttons",
    "list_message",
    "pair_press",
    "sectioned",
    "status_section",
]
