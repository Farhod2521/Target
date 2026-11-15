"""The owners' figures in Telegram: who signed up, who paid, how much, and
what the platform and the office are doing.

Who is an owner here is ``STAFF_BOT_ADMIN_IDS`` - Telegram user ids, set on
the server, not an office role and not a linked cabinet: the card carries
every customer's name and the money, and is asked for from a phone.
``/admin`` (or ``/stat``) answers in either bot, the customers' one and the
office's, and the same card goes out every evening.

The card is a Bot API 10.4 widget: periods behind tabs, drawn inside the
message. A widget has no network, so every figure is put into its HTML
here; one too heavy for Telegram loses list rows until it fits. A client
that cannot draw widgets, or a Telegram that refuses one, gets the same
figures as plain text. The figures are the office dashboard's own
selectors, so the two never disagree.
"""

import logging
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from telegramkit import (
    BotClient,
    Button,
    TelegramError,
    TelegramTemporaryError,
    widget_fits,
)

from app.common.config import settings
from app.common.dates import localtime
from app.common.money import format_minor
from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.backoffice.selectors.dashboard import (
    PaymentRow,
    activity,
    asked_window,
    customers,
    recent_payments,
    takings,
    waiting,
)
from app.modules.billing.constants import InvoiceStatus
from app.modules.billing.models import Invoice
from app.modules.notifications.bot import (
    bot,
    is_configured,
    staff_bot,
    staff_bot_configured,
)

logger = logging.getLogger(__name__)

PERIODS: Final = (("today", "Bugun"), ("7", "7 kun"), ("30", "30 kun"))
SIGNUPS_SHOWN: Final = 8
PAYMENTS_SHOWN: Final = 5
WIDGET_HEIGHT: Final = 600


def is_admin(sender_id: str) -> bool:
    return bool(sender_id) and sender_id in settings.staff_bot_admin_ids


# -- the figures -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Period:
    key: str
    label: str
    signups: int
    signups_change: int | None
    payers: int
    payments: int
    amount: str
    amount_change: int | None
    conversion: int | None
    launched: int
    failed: int
    leads: int
    spend: str
    ai_cost: str
    plans: tuple[tuple[str, int, str], ...]


@dataclass(frozen=True, slots=True)
class Signup:
    when: str
    name: str
    email: str
    phone: str


@dataclass(frozen=True, slots=True)
class Stats:
    stamp: str
    total: int
    paying: int
    trial: int
    expiring: int
    churned: int
    setup_unfinished: int
    meta_missing: int
    unpaid: int
    support: int
    promos: int
    holds: int
    blocks: int
    periods: tuple[Period, ...]
    signups: tuple[Signup, ...]
    paid: tuple[PaymentRow, ...]


def _payers(db: Session, *, since: datetime, until: datetime) -> int:
    """People, not bills: one who paid twice in the window is one payer."""
    return int(
        db.scalar(
            select(func.count(func.distinct(Invoice.owner_id))).where(
                Invoice.archived_at.is_(None),
                Invoice.status == InvoiceStatus.PAID,
                Invoice.paid_at >= since,
                Invoice.paid_at < until,
                or_(Invoice.amount_minor != 0, Invoice.wallet_minor != 0),
            )
        )
        or 0
    )


def read_stats(db: Session, *, now: datetime) -> Stats:
    today = localtime(now).date()
    periods = []
    people = None
    money = None
    for key, label in PERIODS:
        window = asked_window(period=key, since=None, until=None, today=today)
        money = takings(db, window=window, today=today)
        people = customers(db, window=window, now=now)
        done = activity(db, window=window)
        periods.append(
            Period(
                key=key,
                label=label,
                signups=people.joined,
                signups_change=people.joined_change_pct,
                payers=_payers(db, since=window.since, until=window.until),
                payments=money.whole.payments,
                amount=format_minor(
                    amount_minor=money.whole.amount_minor, currency=money.currency
                ),
                amount_change=money.change_pct,
                conversion=people.conversion_pct,
                launched=done.launched,
                failed=done.failed,
                leads=done.leads,
                spend=" · ".join(
                    format_minor(amount_minor=minor, currency=currency)
                    for currency, minor in done.spend[:2]
                )
                or "0",
                ai_cost=format_minor(
                    amount_minor=done.ai_cost_minor, currency=done.ai_currency
                ),
                plans=tuple(
                    (
                        plan.name,
                        plan.payments,
                        format_minor(
                            amount_minor=plan.amount_minor, currency=money.currency
                        ),
                    )
                    for plan in money.whole.plans[:3]
                ),
            )
        )
    assert people is not None and money is not None
    queue = waiting(db, now=now)
    newest = db.scalars(
        select(User)
        .where(User.is_staff.is_(False), User.crm_owner_id.is_(None))
        .order_by(User.date_joined.desc())
        .limit(SIGNUPS_SHOWN)
    )
    return Stats(
        stamp=f"{localtime(now):%d.%m.%Y %H:%M}",
        total=people.total,
        paying=people.paying,
        trial=people.trial,
        expiring=people.expiring,
        churned=people.churned,
        setup_unfinished=people.setup_unfinished,
        meta_missing=people.meta_missing,
        unpaid=money.unpaid,
        support=queue.support,
        promos=queue.promos,
        holds=queue.holds,
        blocks=queue.block_suggestions,
        periods=tuple(periods),
        signups=tuple(
            Signup(
                when=f"{localtime(user.date_joined):%d.%m %H:%M}",
                name=user.full_name or "—",
                email=user.email,
                phone=user.phone,
            )
            for user in newest
        ),
        paid=recent_payments(db)[:PAYMENTS_SHOWN],
    )


# -- the widget ------------------------------------------------------------------

STYLE: Final = """
*{box-sizing:border-box}body{margin:0;font:14px/1.35 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--tx);background:var(--bg)}
:root{--bg:#fff;--tx:#1f2a5c;--mu:#7a84a6;--ln:#e6e9f4;--ac:#3b5bdb;--ok:#2b8a3e;--bad:#c92a2a;--cd:#f5f7ff}
@media(prefers-color-scheme:dark){:root{--bg:#17212b;--tx:#e8ecf5;--mu:#8a97ad;--ln:#2b3a4a;--ac:#6c8cff;--ok:#51cf66;--bad:#ff8787;--cd:#1e2c3a}}
.w{padding:12px}.h{display:flex;justify-content:space-between;color:var(--mu);font-size:12px}
.h b{color:var(--tx);font-size:15px}
.t{display:flex;gap:6px;margin:10px 0}.t button{flex:1;border:1px solid var(--ln);background:none;color:var(--tx);border-radius:8px;padding:6px;font:inherit}
.t button.on{background:var(--ac);color:#fff;border-color:var(--ac)}
.p{display:none}.p.on{display:block}.g{display:grid;grid-template-columns:1fr 1fr;gap:6px}.g3{grid-template-columns:1fr 1fr 1fr}
.c{background:var(--cd);border-radius:10px;padding:7px 8px}.c b{display:block;font-size:18px}
.c span{color:var(--mu);font-size:11px}.m b{color:var(--ok)}.c em{font-style:normal;font-size:11px;margin-left:4px}
.up{color:var(--ok)}.dn{color:var(--bad)}.al b{color:var(--bad)}
h4{margin:12px 0 4px;font-size:12px;color:var(--mu);text-transform:uppercase;letter-spacing:.4px}
.r{display:flex;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px solid var(--ln);font-size:12px}
.r i{color:var(--mu);font-style:normal;white-space:nowrap}.r span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
"""

SCRIPT: Final = """
function s(k){var b=document.querySelectorAll('.t button'),p=document.querySelectorAll('.p');
for(var i=0;i<b.length;i++){b[i].className=b[i].getAttribute('data-k')==k?'on':''}
for(var j=0;j<p.length;j++){p[j].className=p[j].getAttribute('data-k')==k?'p on':'p'}}
if(window.TelegramWidget&&TelegramWidget.ready)TelegramWidget.ready();
"""


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _change(pct: int | None) -> str:
    if pct is None:
        return ""
    return (
        f'<em class="{"up" if pct >= 0 else "dn"}">{"+" if pct >= 0 else ""}{pct}%</em>'
    )


def _card(value: object, label: str, kind: str = "", change: int | None = None) -> str:
    return (
        f'<div class="c {kind}"><b>{_e(value)}{_change(change)}</b>'
        f"<span>{_e(label)}</span></div>"
    )


def _panel(period: Period, first: bool) -> str:
    plans = "".join(
        f'<div class="r"><span>{_e(name)}</span><i>{count} ta · {_e(amount)}</i></div>'
        for name, count, amount in period.plans
    )
    conversion = "—" if period.conversion is None else f"{period.conversion}%"
    return (
        f'<div class="p{" on" if first else ""}" data-k="{period.key}">'
        '<div class="g">'
        + _card(period.signups, "ro'yxatdan o'tdi", change=period.signups_change)
        + _card(period.payers, "obuna to'ladi")
        + _card(period.amount, "tushum", "m", period.amount_change)
        + _card(period.payments, "to'lovlar")
        + '</div><h4>Reklama</h4><div class="g g3">'
        + _card(period.launched, "kampaniya")
        + _card(period.failed, "xato", "al" if period.failed else "")
        + _card(period.leads, "lid")
        + '</div><div class="g" style="margin-top:6px">'
        + _card(period.spend, "reklama sarfi")
        + _card(conversion, "konversiya")
        + "</div>"
        + (f"<h4>Tariflar</h4>{plans}" if plans else "")
        + f'<div class="r"><span>AI xarajati</span><i>{_e(period.ai_cost)}</i></div>'
        + "</div>"
    )


def render_widget(stats: Stats, *, signups: int, payments: int) -> str:
    tabs = "".join(
        f'<button data-k="{p.key}" class="{"on" if i == 0 else ""}" '
        f"onclick=\"s('{p.key}')\">{_e(p.label)}</button>"
        for i, p in enumerate(stats.periods)
    )
    panels = "".join(_panel(p, i == 0) for i, p in enumerate(stats.periods))
    office = (
        _card(stats.support, "javobsiz chat", "al" if stats.support else "")
        + _card(stats.promos, "promo so'rov")
        + _card(stats.unpaid, "to'lanmagan hisob")
        + _card(stats.holds, "ushlangan to'lov", "al" if stats.holds else "")
        + _card(stats.blocks, "blok taklifi", "al" if stats.blocks else "")
        + _card(stats.expiring, "muddati tugaydi")
    )
    base = (
        _card(stats.total, "jami mijoz")
        + _card(stats.paying, "faol obuna", "m")
        + _card(stats.trial, "sinovda")
        + _card(stats.churned, "ketgan")
        + _card(stats.setup_unfinished, "sozlamagan")
        + _card(stats.meta_missing, "Meta ulanmagan")
    )
    joined = "".join(
        f'<div class="r"><span>{_e(row.name)} · {_e(row.email)}</span>'
        f"<i>{_e(row.when)}</i></div>"
        for row in stats.signups[:signups]
    )
    paid = "".join(
        f'<div class="r"><span>{_e(row.email)} · {_e(row.plan)}</span>'
        f"<i>{_e(format_minor(amount_minor=row.amount_minor, currency=row.currency))}</i></div>"
        for row in stats.paid[:payments]
    )
    return (
        f'<style>{STYLE}</style><div class="w">'
        f'<div class="h"><b>TargetologAI · admin</b><span>{_e(stats.stamp)}</span></div>'
        f'<div class="t">{tabs}</div>{panels}'
        f'<h4>Mijozlar</h4><div class="g g3">{base}</div>'
        f'<h4>Ofisni kutmoqda</h4><div class="g g3">{office}</div>'
        + (f"<h4>Oxirgi ro'yxatdan o'tganlar</h4>{joined}" if joined else "")
        + (f"<h4>Oxirgi to'lovlar</h4>{paid}" if paid else "")
        + f"</div><script>{SCRIPT}</script>"
    )


def fitted_widget(stats: Stats) -> str:
    """The richest card Telegram takes: list rows go first when it is heavy."""
    signups, payments = SIGNUPS_SHOWN, PAYMENTS_SHOWN
    while True:
        html = render_widget(stats, signups=signups, payments=payments)
        if widget_fits(html) or (signups == 0 and payments == 0):
            return html
        if signups >= payments and signups:
            signups -= 1
        else:
            payments -= 1


# -- the text --------------------------------------------------------------------


def _t(value: str) -> str:
    """Escaped for a message's HTML, apostrophes left as they are."""
    return escape(value, quote=False)


def render_text(stats: Stats) -> str:
    """The short version: the widget's caption."""
    lines = [f"<b>📊 Admin statistika</b> · {_t(stats.stamp)}"]
    for p in stats.periods:
        lines.append(
            f"<b>{_t(p.label)}:</b> {p.signups} ro'yxatdan o'tdi · "
            f"{p.payers} obuna to'ladi · {_t(p.amount)}"
        )
    lines.append(
        f"Jami mijoz: {stats.total} · faol obuna: {stats.paying} · sinov: {stats.trial}"
    )
    return "\n".join(lines)


def render_full_text(stats: Stats) -> str:
    """Everything the widget shows, for a client that cannot draw one."""
    lines = [f"<b>📊 Admin statistika</b> · {_t(stats.stamp)}"]
    for p in stats.periods:
        conversion = "—" if p.conversion is None else f"{p.conversion}%"
        lines += [
            f"\n<b>{_t(p.label)}</b>",
            f"Ro'yxatdan o'tdi: {p.signups} · obuna to'ladi: {p.payers}",
            f"Tushum: {_t(p.amount)} ({p.payments} to'lov) · konversiya: {conversion}",
            f"Kampaniya: {p.launched} (xato {p.failed}) · lid: {p.leads}",
            f"Reklama sarfi: {_t(p.spend)} · AI: {_t(p.ai_cost)}",
        ]
    lines += [
        "\n<b>Mijozlar</b>",
        f"Jami: {stats.total} · faol obuna: {stats.paying} · sinov: {stats.trial}",
        f"Muddati tugaydi: {stats.expiring} · ketgan: {stats.churned}",
        f"Sozlamagan: {stats.setup_unfinished} · Meta ulanmagan: {stats.meta_missing}",
        "\n<b>Ofisni kutmoqda</b>",
        f"Javobsiz chat: {stats.support} · promo: {stats.promos} · "
        f"to'lanmagan: {stats.unpaid} · ushlangan: {stats.holds} · blok: {stats.blocks}",
    ]
    if stats.signups:
        lines.append("\n<b>Oxirgi ro'yxatdan o'tganlar</b>")
        lines += [
            f"{_t(r.when)} — {_t(r.name)}, {_t(r.email)}"
            + (f", {_t(r.phone)}" if r.phone else "")
            for r in stats.signups
        ]
    if stats.paid:
        lines.append("\n<b>Oxirgi to'lovlar</b>")
        lines += [
            f"{_t(r.email)} — {_t(r.plan)}, "
            f"{_t(format_minor(amount_minor=r.amount_minor, currency=r.currency))}"
            for r in stats.paid
        ]
    return "\n".join(lines)


# -- sending ---------------------------------------------------------------------


def _office_button() -> tuple[Button, ...]:
    return (
        Button(
            text="Ofis paneli",
            url=f"{settings.site_url}{reverse('backoffice:dashboard')}",
        ),
    )


def send_stats(db: Session, *, client: BotClient, chat_id: str, now: datetime) -> str:
    """The card to one owner's chat; plain text when a widget is refused."""
    stats = read_stats(db, now=now)
    try:
        client.send_widget(
            chat_id=chat_id,
            html=fitted_widget(stats),
            caption=render_text(stats),
            height=WIDGET_HEIGHT,
            buttons=_office_button(),
        )
        return "widget"
    except TelegramTemporaryError:
        raise
    except TelegramError as exc:
        logger.warning("admin_stats_widget_refused: %s", exc)
    client.send_message(
        chat_id=chat_id, text=render_full_text(stats), buttons=_office_button()
    )
    return "text"


def _report_bot() -> AbstractContextManager[BotClient] | None:
    """The customers' bot when there is one - the bot the owners already
    have open - and the office's otherwise."""
    if is_configured():
        return bot()
    if staff_bot_configured():
        return staff_bot()
    return None


def deliver_admin_report(db: Session, *, now: datetime) -> int:
    """The evening card to every owner; one unreachable chat skips only itself.
    An owner who never pressed Start in that bot cannot be written to."""
    opened = _report_bot() if settings.staff_bot_admin_ids else None
    if opened is None:
        return 0
    sent = 0
    with opened as client:
        for chat_id in settings.staff_bot_admin_ids:
            try:
                send_stats(db, client=client, chat_id=chat_id, now=now)
                sent += 1
            except TelegramError as exc:
                logger.warning("admin_report_failed for %s: %s", chat_id, exc)
    return sent


__all__ = [
    "deliver_admin_report",
    "fitted_widget",
    "is_admin",
    "read_stats",
    "render_full_text",
    "render_text",
    "send_stats",
]
