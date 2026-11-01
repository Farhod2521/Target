"""One page and account pair's day or week: what the first message's button opens.

The pair's total, where the money was built, and one line per goal: how many,
what one cost, what the goal spent. No campaign, group or advert: «Batafsil»
opens them in the cabinet, on this pair and this period. A week says under each
goal what it came to the week before: comparing is what a week is read for.

The goal lines add up to the total, so a goal nothing here counts has a line
too. It replaces the list in place, and «◀ Ro'yxat» puts the list back. A pair
that is the only one to spend needs no list: its day is the message.

Figures only, like the list - see
:mod:`app.modules.notifications.services.compose_daily`.
"""

from typing import Final
from urllib.parse import urlencode

from telegramkit import Button

from app.common.money import number_format
from app.modules.notifications.keys import daily_list_data, weekly_list_data
from app.modules.notifications.services.compose import (
    Message,
    _bold,
    _italic,
    escaped,
    miniapp_button,
)
from app.modules.notifications.services.compose_daily import (
    SEPARATOR,
    closing_lines,
    compared,
    heading,
    list_buttons,
    list_message,
    pair_press,
    status_line,
)
from core.chat.day_report import DailyReport, DayBook, Result

# What a goal is called on its line. «Murojaat» alone would name two of them.
GOAL_NAMES: Final[dict[str, str]] = {
    "lead": "Forma murojaati",
    "site_lead": "Saytdagi murojaat",
    "chat": "Suhbat",
    "call": "Qo'ng'iroq",
    "view": "Ko'rish",
    "click": "Saytga o'tish",
    "recall": "Eslab qolgan",
    "profile": "Profilga o'tish",
}


def day_view(*, book: DayBook) -> tuple[Message, tuple[Button, ...]]:
    """What the day opens on: the list, or the lone pair's day."""
    report = book.only
    if report is None:
        return list_message(book=book), list_buttons(book=book)
    return pair_message(book=book, report=report), pair_buttons(
        book=book, report=report
    )


def pair_message(*, book: DayBook, report: DailyReport) -> Message:
    """One pair's day, by goal."""
    lone = book.only is report
    if lone:
        lines = [_bold(heading(book)), _bold(report.title)]
    else:
        lines = [_bold(report.title), escaped(report.day_text)]
    if status := status_line(book):
        lines.append(status)
    lines += ["", *_money_lines(book, report)]
    goals = _goal_lines(book, report)
    if goals:
        lines += ["", _bold("Maqsad bo'yicha natijalar"), *goals]
    if report.other_currency:
        spent = SEPARATOR.join(report.other_currency)
        lines += ["", escaped(f"Boshqa valyutada: {spent}")]
    if report.idle:
        lines += [
            "",
            _italic(
                f"Ads Manager'da yana {report.idle} ta kampaniya yoniq, lekin "
                f"{'shu hafta' if book.weekly else f'{report.day_text} kuni'} "
                "sarf qilmadi."
            ),
        ]
    if report.open_proposals:
        lines += [
            "",
            escaped(f"Javob kutayotgan takliflar: {report.open_proposals}"),
        ]
    if lone:
        lines += closing_lines(book)
    return Message(text="\n".join(lines))


def pair_buttons(*, book: DayBook, report: DailyReport) -> tuple[Button, ...]:
    """Back to the list and on to the next pair, then the pair in the cabinet."""
    return (*_steps(book, report), *_cabinet(book, report))


def _steps(book: DayBook, report: DailyReport) -> tuple[Button, ...]:
    if book.only is not None:
        return ()
    spent = book.spent
    place = next(
        (index for index, item in enumerate(spent) if item.pair == report.pair), 0
    )
    following = spent[(place + 1) % len(spent)] if len(spent) > 1 else None
    back = Button(
        text="◀ Ro'yxat",
        data=weekly_list_data(since=book.day)
        if book.weekly
        else daily_list_data(day=book.day, part=0),
    )
    if following is None:
        return (back,)
    return (
        back,
        Button(
            text="Keyingisi ▶",
            data=pair_press(book, following),
        ),
    )


def _cabinet(book: DayBook, report: DailyReport) -> tuple[Button, ...]:
    """This pair over this period: the figures the message gave."""
    query = {"start": book.day.isoformat(), "end": book.until.isoformat()}
    if report.page_id and report.account_id:
        query["pair"] = f"{report.page_id}:{report.account_id}"
    return miniapp_button(
        route="metrics:dashboard",
        label="Batafsil — kabinetda",
        query=urlencode(query),
    )


def _money_lines(book: DayBook, report: DailyReport) -> list[str]:
    if report.spend_minor <= 0:
        return [] if report.other_currency else [_italic("Sarf bo'lmagan")]
    total = f"{escaped('Jami')}: {_bold(report.spend)}{compared(book, report.before)}"
    if not report.elsewhere:
        return [total]
    parts = [
        f"Platformadan {report.here}" if report.here else "",
        f"Ads Manager {report.elsewhere}",
    ]
    return [total, escaped(SEPARATOR.join(part for part in parts if part))]


def _goal_lines(book: DayBook, report: DailyReport) -> list[str]:
    figure = report.figure
    lines: list[str] = []
    for result in figure.results:
        lines.append(_goal_line(result))
        if book.weekly:
            lines.append(_week_before(result))
    if figure.uncounted:
        lines.append(escaped(f"• Natijasi sanalmaydi: sarf {figure.uncounted}"))
    if report.elsewhere_apart:
        lines.append(escaped(f"• Ads Manager: sarf {report.elsewhere}"))
    return lines


def _goal_line(result: Result) -> str:
    name = GOAL_NAMES.get(result.kind, str(result.word))
    if result.count == 0:
        return escaped(f"• {name}: natija yo'q · sarf {result.spend}")
    amount = _amount(result, count=result.count, cost=result.cost)
    return escaped(f"• {name}: {amount} · sarf {result.spend}")


def _week_before(result: Result) -> str:
    if not result.before_spend:
        return escaped("  oldingi hafta: yo'q")
    if result.before_count == 0:
        return escaped("  oldingi hafta: natija yo'q")
    amount = _amount(result, count=result.before_count, cost=result.before_cost)
    return escaped(f"  oldingi hafta: {amount}")


def _amount(result: Result, *, count: int, cost: str) -> str:
    written = number_format(count)
    if result.per_thousand:
        return f"{written} · ming {cost}"
    return f"{written} ta · {cost}"


__all__ = ["day_view", "pair_buttons", "pair_message"]
