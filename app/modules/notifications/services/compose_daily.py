"""The daily report's list, as the message somebody reads on their phone.

Up to five page and account pairs a message, each with what it spent, what
it brought and what one result cost, and a button under it for every pair
that spent. A press replaces the list in place with that pair's day in
full - see :mod:`app.modules.notifications.services.compose_day_pair`.

Figures only. Nothing here judges a day: no verdict, no warning, no reading
by a model. Somebody who wants to know whether a figure is good asks the
assistant, which reads the same figures.

Built by :mod:`app.modules.notifications.services.compose`'s rules: HTML, every
value escaped before it meets a tag, and the figures in the cabinet's own
words - which arrive already translated on the report.
"""

from collections.abc import Sequence
from typing import Final

from telegramkit import Button

from app.common.money import format_minor, number_format
from app.modules.metrics.selectors.results import UNCOUNTED_LABEL
from app.modules.notifications.constants import DAILY_PAIRS_PER_MESSAGE
from app.modules.notifications.keys import daily_pair_data
from app.modules.notifications.services.compose import (
    Message,
    _bold,
    _italic,
    escaped,
    miniapp_button,
)
from core.chat.day_report import DailyReport, Figure, Result

SEPARATOR: Final = " · "
# The longest a pair's name may run on its button before it is cut: a
# phone draws a button one line high and clips the rest anyway.
BUTTON_TITLE_CHARS: Final = 40


def part_count(reports: Sequence[DailyReport]) -> int:
    """How many messages the day's list takes."""
    return max(1, -(-len(reports) // DAILY_PAIRS_PER_MESSAGE))


def list_message(*, reports: Sequence[DailyReport], part: int) -> Message:
    """One message of the day's list: up to five pairs, numbered across all."""
    first = part * DAILY_PAIRS_PER_MESSAGE
    shown = reports[first : first + DAILY_PAIRS_PER_MESSAGE]
    lines = [_bold(_title(reports, part=part))]
    total = _total(reports)
    if total and part == 0:
        lines.append(f"{escaped('Jami sarflandi')}: {_bold(total)}")
    if status := status_line(reports):
        lines.append(status)
    for number, report in enumerate(shown, start=first + 1):
        lines += ["", _bold(f"{number}. {report.title}"), *pair_figures(report)]
    if any(not report.is_quiet for report in shown):
        lines += ["", _italic("Batafsil ko'rish uchun pastdagi tugmani bosing.")]
    return Message(text="\n".join(lines))


def list_buttons(*, reports: Sequence[DailyReport], part: int) -> tuple[Button, ...]:
    """A button for each pair on this message that spent, and the cabinet."""
    first = part * DAILY_PAIRS_PER_MESSAGE
    shown = reports[first : first + DAILY_PAIRS_PER_MESSAGE]
    return (
        *(
            Button(
                text=_button_title(number, report),
                data=daily_pair_data(day=report.day, pair=report.pair),
                row="own",
            )
            for number, report in enumerate(shown, start=first + 1)
            if not report.is_quiet
        ),
        *miniapp_button(route="metrics:dashboard", label="Kabinetda ochish"),
    )


def _title(reports: Sequence[DailyReport], *, part: int) -> str:
    day = reports[0].day_text if reports else ""
    name = "Bugun" if reports and reports[0].ongoing else "Kunlik hisobot"
    title = SEPARATOR.join(bit for bit in (str(name), day) if bit)
    parts = part_count(reports)
    return f"{title}{SEPARATOR}{part + 1}/{parts}" if parts > 1 else title


def _total(reports: Sequence[DailyReport]) -> str:
    """The day's money across every pair, where there is one figure for it.

    Nothing where the pairs pay in two currencies, or where there is only
    one pair and its own line already says it: nothing here converts
    money, and a total that repeats the line under it is noise.
    """
    spent = [report for report in reports if report.spend_minor > 0]
    if len(spent) < 2 or len({report.currency for report in spent}) > 1:
        return ""
    return format_minor(
        amount_minor=sum(report.spend_minor for report in spent),
        currency=spent[0].currency,
    )


def status_line(reports: Sequence[DailyReport]) -> str:
    """Whether these figures are the day's own, or empty when they are.

    Said before anything else about the day: somebody who reads two lines
    and puts the phone down should not act on an afternoon's figures
    believing they are the day's.
    """
    if any(report.ongoing for report in reports):
        return _italic("Kun hali tugamagan — raqamlar shu paytgacha.")
    if any(not report.final for report in reports):
        return _italic("Raqamlar hali yakuniy emas — kun to'liq o'qilmagan.")
    return ""


def pair_figures(report: DailyReport) -> list[str]:
    """Spent, results, and what one cost - three lines, or one when quiet."""
    lines = []
    if report.spend_minor > 0:
        lines += _figure_lines(report.figure)
    elif not report.other_currency:
        lines.append(_italic("Sarf bo'lmagan"))
    if report.other_currency:
        lines.append(
            escaped(
                "Boshqa valyutada: %(spend)s"
                % {"spend": SEPARATOR.join(report.other_currency)}
            )
        )
    return lines


def _figure_lines(figure: Figure) -> list[str]:
    lines = [f"{escaped('Sarflandi')}: {_bold(figure.spend)}"]
    if not figure.counted:
        lines.append(f"{escaped('Natija')}: {escaped(str(UNCOUNTED_LABEL))}")
        return lines
    alone = len(figure.results) == 1
    counts = SEPARATOR.join(_counted(result, alone=alone) for result in figure.results)
    lines.append(f"{escaped('Natija')}: {_bold(counts)}")
    priced = [result for result in figure.results if result.count > 0]
    if len(priced) == 1 and len(figure.results) == 1:
        label = "Mingtasining narxi" if priced[0].per_thousand else "Bittasining narxi"
        lines.append(f"{escaped(label)}: {_bold(priced[0].cost)}")
    elif priced:
        costs = SEPARATOR.join(_priced(result) for result in priced)
        lines.append(f"{escaped('Bittasining narxi')}: {_bold(costs)}")
    return lines


def _counted(result: Result, *, alone: bool) -> str:
    """«41 ta murojaat». Nothing of the only kind is «natija yo'q»; nothing
    of one of two kinds keeps its word, or the line stops saying which."""
    if result.count == 0 and alone:
        return "natija yo'q"
    return "%(count)s ta %(word)s" % {
        "count": number_format(result.count),
        "word": result.word,
    }


def _priced(result: Result) -> str:
    word = (
        "ming %(word)s" % {"word": result.word} if result.per_thousand else result.word
    )
    return f"{word} {result.cost}"


def _button_title(number: int, report: DailyReport) -> str:
    title = f"{number} · {report.title}"
    if len(title) <= BUTTON_TITLE_CHARS:
        return title
    return title[: BUTTON_TITLE_CHARS - 1].rstrip() + "…"


__all__ = [
    "SEPARATOR",
    "list_buttons",
    "list_message",
    "pair_figures",
    "part_count",
    "status_line",
]
