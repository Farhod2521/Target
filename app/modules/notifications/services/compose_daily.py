from collections.abc import Mapping
from typing import Final

from telegramkit import MESSAGE_MAX_CHARS, message_units

from app.common.money import format_minor
from app.common.routes import reverse
from app.modules.notifications.services.compose import (
    Message,
    _bold,
    _folded,
    _italic,
    _link,
    _quote,
    escaped,
)
from core.chat.daily import NO_FIGURE, Census, DailyReport, DayCampaign
from core.chat.day_review import DayReview

SEPARATOR: Final = " · "


def daily_message(*, report: DailyReport, review: DayReview | None) -> Message:
    for count in range(len(report.campaigns), -1, -1):
        text = _assembled(report=report, review=review, count=count)
        if message_units(text) <= MESSAGE_MAX_CHARS:
            return Message(text=text)
    return Message(text=text)


def _assembled(*, report: DailyReport, review: DayReview | None, count: int) -> str:
    lines = _opening(report=report, review=review)
    lines += census_lines(report.day_census)
    lines += attention_lines(report.attention, said=_said(report, review))
    if review is not None and review.advice:
        lines += ["", _quote(review.advice)]
    lines += _folded_list(report, count=count)
    lines += _tail(report)
    return "\n".join(lines)


def _opening(*, report: DailyReport, review: DayReview | None) -> list[str]:
    title = "Kunlik hisobot" if report.page else "Sahifasiz reklamalar"
    named = SEPARATOR.join(
        part for part in (str(title), report.page, report.day_text) if part
    )
    said = review.summary if review is not None else ""
    lines = [_bold(said), escaped(named)] if said else [_bold(named)]
    lines += ["", _figures(report)]
    if not report.final:
        lines.append(_italic("Raqamlar hali yakuniy emas — kun to'liq o'qilmagan."))
    return lines


def _figures(report: DailyReport) -> str:
    parts = [f"{escaped('Sarflandi')}: {_bold(report.spend)}"]
    census = report.day_census
    if census.result_label:
        parts.append(f"{escaped(census.result_label)}: {_bold(str(census.results))}")
    return SEPARATOR.join(parts)


def census_lines(census: Census) -> list[str]:
    if census.spenders < 2:
        return []
    ran = "%(count)d ta kampaniya ishladi" % {"count": census.spenders}
    if census.all_fine:
        return ["", escaped(f"{ran} — {'hammasi joyida'}")]
    parts = []
    if census.fine:
        parts.append("%(count)d joyida" % {"count": census.fine})
    if census.watch:
        parts.append("%(count)d kuzatishda" % {"count": census.watch})
    if census.burning:
        parts.append("%(count)d pul yoqyapti" % {"count": census.burning})
    return ["", escaped(f"{ran}: {', '.join(parts)}")]


def attention_lines(
    rows: tuple[DayCampaign, ...],
    *,
    usual: str = "",
    said: Mapping[DayCampaign, str] | None = None,
) -> list[str]:
    if not rows:
        return []
    lines = ["", _bold("E'tibor talab qiladi")]
    for row in rows:
        lines.append(campaign_row(row, usual=usual))
        if row.cause_label:
            lines.append(_italic(cause_said(row)))
        if line := (said or {}).get(row, ""):
            lines.append(escaped(line))
    return lines


def _said(report: DailyReport, review: DayReview | None) -> dict[DayCampaign, str]:
    if review is None:
        return {}
    return {
        report.campaigns[note.index]: note.line
        for note in review.notes
        if note.index < len(report.campaigns) and note.line
    }


def _folded_list(report: DailyReport, *, count: int) -> list[str]:
    rows = [campaign_row(item) for item in report.campaigns[:count]]
    if not rows:
        return []
    dropped = report.campaigns[count:]
    missing = report.spenders - count
    missing_minor = report.rest_minor + sum(row.spend_minor for row in dropped)
    if missing > 0 and missing_minor > 0:
        rows.append(
            escaped(
                "Yana %(count)d ta kampaniya %(spend)s sarfladi."
                % {
                    "count": missing,
                    "spend": format_minor(
                        amount_minor=missing_minor, currency=report.currency
                    ),
                }
            )
        )
    return ["", _folded("Barcha kampaniyalar", rows)]


def _tail(report: DailyReport) -> list[str]:
    lines = []
    if report.idle:
        lines.append(
            _italic(
                "Hozir yoqilgan %(count)d ta kampaniya kecha pul sarflamagan."
                % {"count": report.idle}
            )
        )
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


def campaign_row(row: DayCampaign, *, usual: str = "") -> str:
    return f"{_bold(f'«{row.name}»')} — {escaped(_outcome(row, usual=usual))}"


def _outcome(row: DayCampaign, *, usual: str) -> str:
    parts = [row.spend]
    if row.kind != "none":
        if row.results == 0:
            parts.append("natija yo'q")
        else:
            parts.append(f"{row.result_label}: {row.results}")
            if row.cost != NO_FIGURE:
                said = row.cost
                if row.usual_cost != NO_FIGURE:
                    said += (
                        f" ({usual % {'value': row.usual_cost}})"
                        if usual
                        else f" ({'odatda'} {row.usual_cost})"
                    )
                parts.append(said)
    if row.learning:
        parts.append("o'rganmoqda")
    return SEPARATOR.join(parts)


def cause_said(row: DayCampaign) -> str:
    if not row.cause_line:
        return row.cause_label
    if row.cause_line.startswith(row.cause_label):
        return row.cause_line
    return f"{row.cause_label} — {row.cause_line}"


__all__ = [
    "attention_lines",
    "campaign_row",
    "cause_said",
    "census_lines",
    "daily_message",
]
