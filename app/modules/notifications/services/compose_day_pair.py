"""One page and account pair's day in full: what the list's button opens.

Every group that spent, «Campaign — Group», with its adverts under it: the
ones switched on now first, the ones switched off since below them, each
half by money. It replaces the list in place, and «◀ Ro'yxat» puts the list
back.

Figures only, like the list - see :mod:`app.modules.notifications.services.compose_daily`.
"""

from collections.abc import Sequence

from telegramkit import MESSAGE_MAX_CHARS, Button, message_units

from app.common.money import format_minor, number_format
from app.modules.metrics.selectors.results import UNCOUNTED_LABEL
from app.modules.notifications.constants import DAILY_PAIRS_PER_MESSAGE
from app.modules.notifications.keys import daily_list_data, daily_pair_data
from app.modules.notifications.services.compose import (
    Message,
    _bold,
    _italic,
    escaped,
    miniapp_button,
)
from app.modules.notifications.services.compose_daily import (
    SEPARATOR,
    pair_figures,
    status_line,
)
from core.chat.day_report import DailyReport, Figure, GroupLine


def pair_message(*, report: DailyReport, number: int) -> Message:
    """One pair's day in full, cut to fit rather than cut off.

    Telegram takes four thousand characters. A pair with more groups than
    that loses the adverts under its smallest groups first, then those
    groups themselves - and a last line says what the dropped ones spent,
    so the rows still add up to the figure at the top.
    """
    size = len(report.groups)
    for with_ads in range(size, -1, -1):
        text = _pair_text(report, number=number, shown=size, with_ads=with_ads)
        if message_units(text) <= MESSAGE_MAX_CHARS:
            return Message(text=text)
    for shown in range(size - 1, -1, -1):
        text = _pair_text(report, number=number, shown=shown, with_ads=0)
        if message_units(text) <= MESSAGE_MAX_CHARS:
            return Message(text=text)
    return Message(text=text)


def pair_buttons(*, reports: Sequence[DailyReport], index: int) -> tuple[Button, ...]:
    """Back to the list, on to the next pair that spent, and the cabinet."""
    report = reports[index]
    spent = [place for place, item in enumerate(reports) if not item.is_quiet]
    after = [place for place in spent if place > index] + spent
    following = next((place for place in after if place != index), None)
    buttons = [
        Button(
            text="◀ Ro'yxat",
            data=daily_list_data(day=report.day, part=index // DAILY_PAIRS_PER_MESSAGE),
        )
    ]
    if following is not None:
        buttons.append(
            Button(
                text="Keyingisi ▶",
                data=daily_pair_data(day=report.day, pair=reports[following].pair),
            )
        )
    return (
        *buttons,
        *miniapp_button(route="metrics:dashboard", label="Kabinetda ochish"),
    )


def _pair_text(report: DailyReport, *, number: int, shown: int, with_ads: int) -> str:
    """The pair's message with ``shown`` groups, the first ``with_ads`` of
    them with their adverts."""
    lines = [_bold(f"{number}. {report.title}"), escaped(report.day_text)]
    if status := status_line([report]):
        lines.append(status)
    lines += ["", *pair_figures(report)]
    if report.groups:
        lines.append(
            _italic(
                "%(campaigns)s kampaniya · %(groups)s guruh · "
                "%(ads)s reklama ishladi"
                % {
                    "campaigns": report.campaigns,
                    "groups": len(report.groups),
                    "ads": report.ad_count,
                }
            )
        )
        lines += ["", _italic("Har qatorda: natija · bittasining narxi · sarf")]
    kept = report.groups[:shown]
    for heading, running in (
        ("Hozir yoqilgan", True),
        ("Ishlagan, hozir o'chirilgan", False),
    ):
        half = [
            (place, group)
            for place, group in enumerate(kept)
            if group.running is running
        ]
        if half:
            lines += ["", _bold(heading)]
        for place, group in half:
            lines += ["", *_group_lines(group, with_ads=place < with_ads)]
    lines += _dropped(report, shown=shown)
    lines += _footnotes(report)
    return "\n".join(lines)


def _group_lines(group: GroupLine, *, with_ads: bool) -> list[str]:
    name = (
        f"{group.campaign} — {group.name}"
        if group.campaign and group.name
        else group.campaign or group.name
    )
    lines = [
        _bold(name),
        f"{escaped(_row_result(group.figure, short=False))}{_bold(group.figure.spend)}",
    ]
    if not with_ads:
        return lines
    for place, ad in enumerate(group.ads):
        branch = "└" if place == len(group.ads) - 1 else "├"
        lines.append(
            escaped(
                f"{branch} {ad.name}: {_row_result(ad.figure, short=True)}"
                f"{ad.figure.spend}"
            )
        )
    return lines


def _row_result(figure: Figure, *, short: bool) -> str:
    """«22 murojaat · $2.05 · », the start of a row; the spend follows it.

    ``short`` drops the word, for an advert under a group that already
    said it.
    """
    if not figure.counted:
        return f"{UNCOUNTED_LABEL}{SEPARATOR}"
    parts = []
    for result in figure.results:
        if result.count == 0:
            parts.append("natija yo'q")
            continue
        count = number_format(result.count)
        parts += [count if short else f"{count} {result.word}", result.cost]
    return SEPARATOR.join(parts) + SEPARATOR if parts else ""


def _dropped(report: DailyReport, *, shown: int) -> list[str]:
    left = report.groups[shown:]
    if not left:
        return []
    spend = format_minor(
        amount_minor=sum(group.figure.spend_minor for group in left),
        currency=report.currency,
    )
    return [
        "",
        _italic(
            "Yana %(count)s ta guruh %(spend)s sarfladi — kabinetda."
            % {"count": len(left), "spend": spend}
        ),
    ]


def _footnotes(report: DailyReport) -> list[str]:
    """What the cabinet draws on this pair and the figures above leave out."""
    lines = []
    if report.unplaced:
        lines.append(
            _italic(
                "Sahifasi aniq yozilmagan reklamalaringiz yana %(spend)s "
                "sarfladi. Ular kabinetda ko'rinadi, lekin bu hisobotga "
                "kirmaydi." % {"spend": report.unplaced}
            )
        )
    return ["", *lines] if lines else []


__all__ = ["pair_buttons", "pair_message"]
