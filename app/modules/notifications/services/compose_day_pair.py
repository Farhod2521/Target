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
from app.modules.ads.constants import CONVERSION_EVENT_LABELS
from app.modules.chat.selectors.day_lines import SITE_EVENT
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
    closing_sections,
    compared,
    heading,
    list_buttons,
    list_message,
    list_parts,
    pair_press,
    part_of,
    sectioned,
    status_section,
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
    "registration": "Ro'yxatdan o'tish",
    "message_purchase": "Xabar orqali xarid",
}


def day_view(*, book: DayBook, part: int = 0) -> tuple[Message, tuple[Button, ...]]:
    """What a message of the day opens on: its list, or the lone pair's day. A
    part the list no longer has - it can shrink before the day is final - is
    its last."""
    report = book.only
    if report is None:
        part = min(part, len(list_parts(book)) - 1)
        return list_message(book=book, part=part), list_buttons(book=book, part=part)
    return pair_message(book=book, report=report), pair_buttons(
        book=book, report=report
    )


def day_views(*, book: DayBook) -> tuple[tuple[Message, tuple[Button, ...]], ...]:
    """Every message the day is sent as, in order."""
    return tuple(
        day_view(book=book, part=part) for part in range(len(list_parts(book)))
    )


def pair_message(*, book: DayBook, report: DailyReport) -> Message:
    """One pair's period, by goal."""
    lone = book.only is report
    return Message(
        text=sectioned(
            _head(book, report, lone=lone),
            _money_lines(book, report),
            _goal_section(book, report),
            _notes(book, report),
            *(closing_sections(book) if lone else []),
            status_section(book),
        )
    )


def _head(book: DayBook, report: DailyReport, *, lone: bool) -> list[str]:
    lines = [heading(book)] if lone else []
    lines.append(f"📄 {_bold(report.page or report.title)}")
    if report.account and report.account != report.page:
        lines.append(escaped(f"Akkaunt: {report.account}"))
    return [*lines, escaped(report.day_text)]


def _notes(book: DayBook, report: DailyReport) -> list[str]:
    lines = []
    if report.other_currency:
        spent = SEPARATOR.join(report.other_currency)
        lines.append(escaped(f"Boshqa valyutada: {spent}"))
    if report.idle:
        when = "shu hafta" if book.weekly else "shu kuni"
        lines.append(
            _italic(
                f"Ads Manager'da yana {report.idle} ta kampaniya yoniq, lekin "
                f"{when} sarf qilmadi"
            )
        )
    if report.open_proposals:
        lines.append(escaped(f"Javob kutayotgan takliflar: {report.open_proposals}"))
    return lines


def pair_buttons(*, book: DayBook, report: DailyReport) -> tuple[Button, ...]:
    """Back to the list and on to the next pair of the same message, so one
    message never ends up showing what another does; then the cabinet."""
    return (*_steps(book, report), *_cabinet(book, report))


def _steps(book: DayBook, report: DailyReport) -> tuple[Button, ...]:
    if book.only is not None:
        return ()
    part = part_of(book, report)
    spent = list_parts(book)[part]
    place = next(
        (index for index, item in enumerate(spent) if item.pair == report.pair), 0
    )
    following = spent[(place + 1) % len(spent)] if len(spent) > 1 else None
    back = Button(
        text="◀ Ro'yxat",
        data=weekly_list_data(since=book.day, part=part)
        if book.weekly
        else daily_list_data(day=book.day, part=part),
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
    lines = [f"💰 {_bold(f'Jami sarf: {report.spend}')}"]
    if line := compared(book, report.before, report.change):
        lines.append(line)
    if report.here and report.elsewhere:
        lines.append(_row("Platformadan", report.here))
    if report.elsewhere:
        lines.append(_row("Ads Manager", report.elsewhere))
    return lines


def _goal_section(book: DayBook, report: DailyReport) -> list[str]:
    figure = report.figure
    cards = [_goal_card(book, result) for result in figure.results]
    if figure.uncounted:
        cards.append(_card("Natijasi sanalmaydi", _row("Sarf", figure.uncounted)))
    if report.elsewhere_apart:
        cards.append(_card("Ads Manager", _row("Sarf", report.elsewhere)))
    if not cards:
        return []
    return [f"🎯 {_bold('NATIJALAR')}", "", "\n\n".join(cards)]


def _card(name: str, *rows: str) -> str:
    """One goal, set apart: Telegram draws a quote with a bar down its side.
    The rows arrive escaped, so ``_quote`` would escape their tags again."""
    body = "\n".join([_bold(name), *rows])
    return f"<blockquote>{body}</blockquote>"


def _row(label: str, value: str) -> str:
    return f"{escaped(label)}: {_bold(value)}"


def _site_event_name(kind: str) -> str:
    """TZ 3: a site event under its own name - «Xarid», «Obuna bo'lish»."""
    if kind.startswith(SITE_EVENT):
        return str(
            CONVERSION_EVENT_LABELS.get(kind.removeprefix(SITE_EVENT), "Boshqa natija")
        )
    return "Boshqa natija"


def _goal_card(book: DayBook, result: Result) -> str:
    name = GOAL_NAMES.get(result.kind) or _site_event_name(result.kind)
    if result.count == 0:
        rows = [_row("Natija", "yo'q")]
    else:
        rows = [
            _row("Natija", f"{number_format(result.count)} ta"),
            _row("Mingtasi" if result.per_thousand else "Narxi", result.cost),
        ]
    rows.append(_row("Sarf", result.spend))
    if book.weekly:
        rows.append(escaped(_week_before(result)))
    return _card(name, *rows)


def _week_before(result: Result) -> str:
    if not result.before_spend:
        return "Oldingi hafta: yo'q"
    if result.before_count == 0:
        return "Oldingi hafta: natija yo'q"
    count = number_format(result.before_count)
    return f"Oldingi hafta: {count} ta · {result.before_cost}"


__all__ = ["day_view", "day_views", "pair_buttons", "pair_message"]
