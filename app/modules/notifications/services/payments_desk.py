"""The payments group: a receipt for every paid bill, and the totals by plan
once a day, a week and a month have ended.

Only a bill that is paid, on the books and took money counts: one still held,
canceled, expired, refunded, archived, or covered whole by credit or balance
never reaches the group. Uzbek, like the office: the readers are the team.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.orm import Session, joinedload
from telegramkit import TelegramError

from app.common.cache import cache
from app.common.config import settings
from app.common.dates import date_format, localtime, office_zone
from app.common.i18n import override
from app.common.money import format_minor_parts
from app.common.routes import reverse
from app.modules.billing.constants import (
    INVOICE_KIND_LABELS,
    MANUAL_METHOD_LABELS,
    InvoiceKind,
    InvoiceStatus,
    TransactionState,
)
from app.modules.billing.models import Invoice, PaymentTransaction, Plan
from app.modules.notifications.bot import (
    payments_bot,
    payments_bot_configured,
    payments_chat_id,
    payments_thread_id,
)
from app.modules.notifications.constants import (
    PAYMENTS_REPORT_KEY,
    PAYMENTS_REPORT_LATEST_HOUR,
    PAYMENTS_REPORT_SENT_SECONDS,
    RECEIPT_LOOKBACK_HOURS,
)
from app.modules.notifications.services.compose import escaped

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "payme": "Payme",
    "click": "Click",
    "paynet": "Paynet",
    "multicard": "Multicard",
}
DAY, WEEK, MONTH = "day", "week", "month"
PERIOD_TITLES = {
    DAY: "Kunlik hisobot",
    WEEK: "Haftalik hisobot",
    MONTH: "Oylik hisobot",
}


def _counted(*, since: datetime | None = None) -> tuple[ColumnElement[bool], ...]:
    where: tuple[ColumnElement[bool], ...] = (
        Invoice.status == InvoiceStatus.PAID,
        Invoice.archived_at.is_(None),
        Invoice.amount_minor > 0,
    )
    return where if since is None else (*where, Invoice.paid_at >= since)


# -- receipts ---------------------------------------------------------------


def send_receipts(db: Session, *, now: datetime) -> int:
    """Post every receipt still owed, oldest first. Returns how many went."""
    if not payments_bot_configured():
        return 0
    since = now - timedelta(hours=RECEIPT_LOOKBACK_HOURS)
    owed = list(
        db.scalars(
            select(Invoice.id)
            .where(*_counted(since=since), Invoice.receipt_sent_at.is_(None))
            .order_by(Invoice.paid_at)
        )
    )
    sent = 0
    with payments_bot() as client, override("uz"):
        for invoice_id in owed:
            invoice = db.get(Invoice, invoice_id)
            if invoice is None:
                continue
            text = receipt_text(db, invoice=invoice)
            if not _claim(db, invoice_id=invoice_id, now=now):
                continue
            try:
                client.send_message(
                    chat_id=payments_chat_id(),
                    text=text,
                    thread_id=payments_thread_id(),
                )
            except TelegramError:
                # The group or the bot is at fault, not this bill: the rest
                # would fail the same way. The next minute tries again.
                logger.warning("receipt not posted", extra={"invoice": invoice.number})
                _release(db, invoice_id=invoice_id)
                break
            sent += 1
    return sent


def _claim(db: Session, *, invoice_id: object, now: datetime) -> bool:
    """Mark the receipt sent before it goes, so two runs never both post it."""
    claimed = db.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id, Invoice.receipt_sent_at.is_(None))
        .values(receipt_sent_at=now, updated_at=Invoice.updated_at)
    ).rowcount
    db.commit()
    return bool(claimed)


def _release(db: Session, *, invoice_id: object) -> None:
    db.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id)
        .values(receipt_sent_at=None, updated_at=Invoice.updated_at)
    )
    db.commit()


def receipt_text(db: Session, *, invoice: Invoice) -> str:
    owner = invoice.owner
    lines = [
        "✅ <b>To'lov qabul qilindi</b>",
        "",
        f"<b>Summa:</b> {escaped(_money(invoice.amount_minor, invoice.currency))}",
    ]
    if invoice.wallet_minor > 0:
        lines.append(
            f"<b>Balansdan:</b> {escaped(_money(invoice.wallet_minor, invoice.currency))}"
        )
    lines += [
        f"<b>Nima uchun:</b> {escaped(_bought(invoice))}",
        f"<b>Mijoz:</b> {escaped(_customer(invoice))}",
        f"<b>Usul:</b> {escaped(_method(db, invoice=invoice))}",
        f"<b>Hisob raqami:</b> <code>{escaped(invoice.number)}</code>",
    ]
    if invoice.paid_at is not None:
        paid = date_format(localtime(invoice.paid_at), "d.m.Y H:i")
        lines.append(f"<b>Vaqt:</b> {paid}")
    if owner is not None:
        path = reverse("backoffice:customer", kwargs={"customer_id": owner.id})
        lines += [
            "",
            f'<a href="{escaped(settings.site_url + path)}">Ofisda ochish</a>',
        ]
    return "\n".join(lines)


def _bought(invoice: Invoice) -> str:
    if invoice.kind == InvoiceKind.PAGES:
        return f"{INVOICE_KIND_LABELS[InvoiceKind.PAGES]} · {invoice.pages} ta"
    if invoice.kind == InvoiceKind.SEATS:
        return f"{INVOICE_KIND_LABELS[InvoiceKind.SEATS]} · {invoice.seats} ta"
    parts = [f"{invoice.plan.name} tarifi"]
    if invoice.period_days:
        parts.append(f"{invoice.period_days} kun")
    if invoice.pages:
        parts.append(f"+{invoice.pages} sahifa")
    if invoice.seats:
        parts.append(f"+{invoice.seats} menejer")
    return " · ".join(parts)


def _customer(invoice: Invoice) -> str:
    owner = invoice.owner
    if owner is None:
        return invoice.former_email or "-"
    return " · ".join(
        part for part in (owner.full_name, owner.email, owner.phone) if part
    )


def _method(db: Session, *, invoice: Invoice) -> str:
    if invoice.manual_method:
        label = MANUAL_METHOD_LABELS.get(invoice.manual_method, invoice.manual_method)
        return f"{label} (ofisda yozildi)"
    provider = db.scalar(
        select(PaymentTransaction.provider)
        .where(
            PaymentTransaction.invoice_id == invoice.id,
            PaymentTransaction.state == TransactionState.PERFORMED,
        )
        .order_by(PaymentTransaction.performed_at.desc())
        .limit(1)
    )
    if not provider:
        return "-"
    return PROVIDER_LABELS.get(provider, provider)


def _money(amount_minor: int, currency: str) -> str:
    parts = format_minor_parts(amount_minor=amount_minor, currency=currency)
    if currency == "UZS":
        return f"{parts.amount} so'm"
    return str(parts)


# -- reports ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Period:
    kind: str
    start: date
    end: date  # the first day after it

    @property
    def title(self) -> str:
        last = self.end - timedelta(days=1)
        if self.kind == DAY:
            span = date_format(self.start, "d.m.Y")
        elif self.kind == MONTH:
            span = date_format(self.start, "F Y").capitalize()
        else:
            span = f"{date_format(self.start, 'd.m')} – {date_format(last, 'd.m.Y')}"
        return f"{PERIOD_TITLES[self.kind]} · {span}"


@dataclass(slots=True)
class Line:
    label: str
    order: tuple[int, int, str]
    buyers: set[object] = field(default_factory=set)
    payments: int = 0
    sums: dict[str, int] = field(default_factory=dict)


def finished_periods(*, today: date) -> list[Period]:
    """What ended at midnight before ``today``: always the day, the week on a
    Monday, the month on the first."""
    periods = [Period(kind=DAY, start=today - timedelta(days=1), end=today)]
    if today.weekday() == 0:
        periods.append(Period(kind=WEEK, start=today - timedelta(days=7), end=today))
    if today.day == 1:
        start = (today - timedelta(days=1)).replace(day=1)
        periods.append(Period(kind=MONTH, start=start, end=today))
    return periods


def send_reports(db: Session, *, now: datetime) -> int:
    """Hourly: the totals of every period that ended last midnight, once each,
    until the office's early morning is over."""
    if not payments_bot_configured():
        return 0
    local = localtime(now)
    if local.hour >= PAYMENTS_REPORT_LATEST_HOUR:
        return 0
    sent = 0
    with payments_bot() as client, override("uz"):
        for period in finished_periods(today=local.date()):
            key = PAYMENTS_REPORT_KEY.format(kind=period.kind, start=period.start)
            text = report_text(db, period=period)
            if not cache.add(key, "1", PAYMENTS_REPORT_SENT_SECONDS):
                continue
            try:
                client.send_message(
                    chat_id=payments_chat_id(),
                    text=text,
                    thread_id=payments_thread_id(),
                )
            except TelegramError:
                cache.delete(key)
                logger.warning(
                    "payments report not posted",
                    extra={"kind": period.kind, "start": str(period.start)},
                )
                break
            sent += 1
    return sent


def report_text(db: Session, *, period: Period) -> str:
    lines = [f"📊 <b>{escaped(period.title)}</b>", ""]
    invoices = _paid_between(
        db, start=_midnight(period.start), end=_midnight(period.end)
    )
    if not invoices:
        lines.append("To'lov bo'lmadi.")
        return "\n".join(lines)
    total: dict[str, int] = {}
    for invoice in invoices:
        total[invoice.currency] = total.get(invoice.currency, 0) + invoice.amount_minor
    buyers = {invoice.owner_id or invoice.former_email for invoice in invoices}
    lines += [
        f"Jami: <b>{escaped(_sums(total))}</b>",
        f"To'lovlar: {len(invoices)} ta · {len(buyers)} kishi",
        "",
        "<b>Tariflar bo'yicha:</b>",
    ]
    for line in _by_plan(invoices):
        said = f"• {escaped(line.label)} — {len(line.buyers)} kishi"
        if line.payments != len(line.buyers):
            said += f" ({line.payments} ta to'lov)"
        lines.append(f"{said} · {escaped(_sums(line.sums))}")
    return "\n".join(lines)


def _by_plan(invoices: Sequence[Invoice]) -> list[Line]:
    """One line per plan, and the extra pages and CRM managers after them."""
    lines: dict[str, Line] = {}
    for invoice in invoices:
        if invoice.kind == InvoiceKind.PLAN:
            plan: Plan = invoice.plan
            key = f"plan:{plan.id}"
            label, order = plan.name, (0, plan.sort_order, plan.name)
        else:
            key = f"kind:{invoice.kind}"
            label = INVOICE_KIND_LABELS.get(invoice.kind, invoice.kind)
            order = (1, 0 if invoice.kind == InvoiceKind.PAGES else 1, label)
        line = lines.setdefault(key, Line(label=label, order=order))
        line.buyers.add(invoice.owner_id or invoice.former_email)
        line.payments += 1
        line.sums[invoice.currency] = (
            line.sums.get(invoice.currency, 0) + invoice.amount_minor
        )
    return sorted(lines.values(), key=lambda line: line.order)


def _paid_between(db: Session, *, start: datetime, end: datetime) -> list[Invoice]:
    return list(
        db.scalars(
            select(Invoice)
            .options(joinedload(Invoice.plan))
            .where(*_counted(since=start), Invoice.paid_at < end)
            .order_by(Invoice.paid_at)
        )
    )


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=office_zone())


def _sums(sums: dict[str, int]) -> str:
    """Two currencies never add: each is said on its own."""
    return " + ".join(
        _money(amount, currency) for currency, amount in sorted(sums.items())
    )
