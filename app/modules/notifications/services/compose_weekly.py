from typing import Final

from telegramkit import MESSAGE_MAX_CHARS, message_units

from app.common.money import format_minor
from app.common.routes import reverse
from app.modules.notifications.services.compose import (
    EN_DASH,
    Message,
    _bold,
    _folded,
    _italic,
    _kind_line,
    _link,
    _quote,
    escaped,
)
from app.modules.notifications.services.compose_daily import (
    attention_lines,
    campaign_row,
    census_lines,
)
from core.chat.report import WeeklyReport

SEPARATOR: Final = " · "


def weekly_message(*, report: WeeklyReport, summary: str, advice: str) -> Message:
    text = ""
    for count in range(len(report.campaigns), -1, -1):
        text = _assembled(report=report, summary=summary, advice=advice, count=count)
        if message_units(text) <= MESSAGE_MAX_CHARS:
            break
    return Message(text=text)


def _assembled(*, report: WeeklyReport, summary: str, advice: str, count: int) -> str:
    lines = _opening(report=report, summary=summary)
    lines += census_lines(report.census)
    lines += attention_lines(report.attention, usual="oldingi hafta: %(value)s")
    if advice:
        lines += ["", _quote(advice)]
    lines += _best(report)
    lines += _folded_list(report, count=count)
    lines += _tail(report)
    return "\n".join(lines)


def _opening(*, report: WeeklyReport, summary: str) -> list[str]:
    named = SEPARATOR.join(
        part
        for part in (
            "Haftalik hisobot",
            report.page,
            f"{report.since} {EN_DASH} {report.until}",
        )
        if part
    )
    lines = [_bold(summary), escaped(named)] if summary else [_bold(named)]
    lines += ["", *_figures(report)]
    if not report.final:
        lines.append(_italic("Raqamlar hali yakuniy emas — kun to'liq o'qilmagan."))
    if report.spent_for_nothing:
        lines += ["", escaped("Pul sarflandi, natija bo'lmadi.")]
    return lines


def _figures(report: WeeklyReport) -> list[str]:
    now, before = (report.now, report.before)
    compared = before.spend_minor > 0
    lines = [_figure("Sarflandi", now.spend, before.spend if compared else "")]
    if len(now.kinds) < 2:
        lines += [
            _figure(
                now.result_label,
                str(now.results),
                str(before.results) if compared else "",
            ),
            _figure(
                now.result_cost_label,
                now.result_cost,
                before.result_cost if compared else "",
            ),
        ]
    else:
        lines += [_kind_line(row) for row in now.kinds]
    return lines


def _figure(label: object, value: str, before: str) -> str:
    line = f"{escaped(str(label))}: {_bold(value)}"
    if before:
        line += " " + _italic(
            "(" + str("oldingi hafta: %(value)s" % {"value": before}) + ")"
        )
    return line


def _best(report: WeeklyReport) -> list[str]:
    if report.best is None:
        return []
    return [
        "",
        escaped(
            "Eng ko'p %(what)s: %(name)s — %(qty)s ta"
            % {
                "what": report.best.label,
                "name": f"«{report.best.name}»",
                "qty": report.best.results,
            }
        ),
    ]


def _folded_list(report: WeeklyReport, *, count: int) -> list[str]:
    rows = [
        campaign_row(item, usual="oldingi hafta: %(value)s")
        for item in report.campaigns[:count]
    ]
    if not rows:
        return []
    dropped = report.campaigns[count:]
    if dropped:
        rows.append(
            escaped(
                "Yana %(count)d ta kampaniya %(spend)s sarfladi."
                % {
                    "count": len(dropped),
                    "spend": format_minor(
                        amount_minor=sum(row.spend_minor for row in dropped),
                        currency=report.currency,
                    ),
                }
            )
        )
    return ["", _folded("Barcha kampaniyalar", rows)]


def _tail(report: WeeklyReport) -> list[str]:
    lines = []
    if report.open_proposals:
        lines.append(
            _italic(
                "Javob kutayotgan takliflar: %(count)d"
                % {"count": report.open_proposals}
            )
        )
    if report.elsewhere:
        lines.append(
            _italic(
                "Ads Manager'da yaratilgan reklamalaringiz yana %(spend)s sarfladi. Ular bu hisobotga kirmaydi."
                % {"spend": report.elsewhere}
            )
        )
    if report.other_currency:
        lines.append(
            _italic(
                "Boshqa valyutada ham to'langan: %(spend)s. U yuqoridagi raqamlarga qo'shilmagan."
                % {"spend": " · ".join(report.other_currency)}
            )
        )
    if lines:
        lines.insert(0, "")
    opened = _link(path=reverse("metrics:dashboard"), label="Kabinetda ochish")
    return [*lines, "", opened]


__all__ = ["weekly_message"]
