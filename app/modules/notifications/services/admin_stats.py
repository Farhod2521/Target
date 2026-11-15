"""The owners' figures in the staff bot: who signed up, who paid, how much.

Who is an owner here is ``STAFF_BOT_ADMIN_IDS`` - Telegram user ids, set on
the server, not an office role: the card carries every customer's name and
the money, and is asked for from a phone. ``/stat`` answers on demand, and
the same card goes out every evening.

The card is a Bot API 10.4 widget: three periods behind tabs, drawn inside
the message. A widget has no network, so every figure is put into its HTML
here; one too heavy for Telegram loses list rows until it fits. A client
that cannot draw widgets, or a Telegram that refuses one, gets the same
figures as plain text.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from telegramkit import BotClient, TelegramError, TelegramTemporaryError, widget_fits

from app.common.config import settings
from app.common.dates import localtime
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.backoffice.selectors.dashboard import (
    PaymentRow,
    asked_window,
    recent_payments,
    takings,
)
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Subscription
from app.modules.notifications.bot import staff_bot, staff_bot_configured

logger = logging.getLogger(__name__)

PERIODS: Final = (("today", "Bugun"), ("7", "7 kun"), ("30", "30 kun"))
SIGNUPS_SHOWN: Final = 8
PAYMENTS_SHOWN: Final = 5
WIDGET_HEIGHT: Final = 520


def is_admin(sender_id: str) -> bool:
    return bool(sender_id) and sender_id in settings.staff_bot_admin_ids


@dataclass(frozen=True, slots=True)
class Period:
    key: str
    label: str
    signups: int
    payments: int
    payers: int
    amount: str
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
    customers: int
    paying: int
    trial: int
    periods: tuple[Period, ...]
    signups: tuple[Signup, ...]
    paid: tuple[PaymentRow, ...]


def _customer() -> object:
    return (User.is_staff.is_(False)) & (User.crm_owner_id.is_(None))


def read_stats(db: Session, *, now: datetime) -> Stats:
    today = localtime(now).date()
    periods = []
    for key, label in PERIODS:
        window = asked_window(period=key, since=None, until=None, today=today)
        found = takings(db, window=window, today=today)
        # People, not bills: one who paid twice in the window is one payer.
        payers = db.scalar(
            select(func.count(func.distinct(Invoice.owner_id))).where(
                Invoice.archived_at.is_(None),
                Invoice.status == InvoiceStatus.PAID,
                Invoice.paid_at >= window.since,
                Invoice.paid_at < window.until,
                or_(Invoice.amount_minor != 0, Invoice.wallet_minor != 0),
            )
        )
        periods.append(
            Period(
                key=key,
                label=label,
                signups=found.whole.signups,
                payments=found.whole.payments,
                payers=int(payers or 0),
                amount=format_minor(
                    amount_minor=found.whole.amount_minor, currency=found.currency
                ),
                plans=tuple(
                    (
                        plan.name,
                        plan.payments,
                        format_minor(
                            amount_minor=plan.amount_minor, currency=found.currency
                        ),
                    )
                    for plan in found.whole.plans[:3]
                ),
            )
        )
    customers = db.scalar(select(func.count(User.id)).where(_customer()))  # type: ignore[arg-type]
    live = dict(
        db.execute(
            select(
                Subscription.status, func.count(func.distinct(Subscription.owner_id))
            )
            .where(
                Subscription.status.in_(
                    (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL)
                ),
                Subscription.expires_at > now,
            )
            .group_by(Subscription.status)
        ).all()
    )
    newest = db.scalars(
        select(User)
        .where(_customer())  # type: ignore[arg-type]
        .order_by(User.date_joined.desc())
        .limit(SIGNUPS_SHOWN)
    )
    return Stats(
        stamp=f"{localtime(now):%d.%m.%Y %H:%M}",
        customers=int(customers or 0),
        paying=int(live.get(SubscriptionStatus.ACTIVE, 0)),
        trial=int(live.get(SubscriptionStatus.TRIAL, 0)),
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
*{box-sizing:border-box}body{margin:0;font:14px/1.35 -apple-system,Segoe UI,Roboto,sans-serif;
color:var(--tx);background:var(--bg)}
:root{--bg:#fff;--tx:#1f2a5c;--mu:#7a84a6;--ln:#e6e9f4;--ac:#3b5bdb;--ok:#2b8a3e}
@media(prefers-color-scheme:dark){:root{--bg:#17212b;--tx:#e8ecf5;--mu:#8a97ad;--ln:#2b3a4a;--ac:#6c8cff;--ok:#51cf66}}
.w{padding:12px}.h{display:flex;justify-content:space-between;color:var(--mu);font-size:12px}
.t{display:flex;gap:6px;margin:10px 0}.t button{flex:1;border:1px solid var(--ln);background:none;
color:var(--tx);border-radius:8px;padding:6px;font:inherit}.t button.on{background:var(--ac);color:#fff;border-color:var(--ac)}
.p{display:none}.p.on{display:block}.g{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.c{border:1px solid var(--ln);border-radius:10px;padding:8px}.c b{display:block;font-size:20px}
.c span{color:var(--mu);font-size:12px}.m b{color:var(--ok)}
h4{margin:12px 0 4px;font-size:13px;color:var(--mu)}.r{display:flex;justify-content:space-between;
gap:8px;padding:4px 0;border-bottom:1px solid var(--ln);font-size:13px}.r i{color:var(--mu);font-style:normal}
.r span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
"""

SCRIPT: Final = """
function s(k){var b=document.querySelectorAll('.t button'),p=document.querySelectorAll('.p');
for(var i=0;i<b.length;i++){b[i].className=b[i].getAttribute('data-k')==k?'on':''}
for(var j=0;j<p.length;j++){p[j].className=p[j].getAttribute('data-k')==k?'p on':'p'}}
if(window.TelegramWidget&&TelegramWidget.ready)TelegramWidget.ready();
"""


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _card(value: object, label: str, money: bool = False) -> str:
    return f'<div class="c{" m" if money else ""}"><b>{_e(value)}</b><span>{_e(label)}</span></div>'


def _panel(period: Period, first: bool) -> str:
    plans = "".join(
        f'<div class="r"><span>{_e(name)}</span><i>{count} ta · {_e(amount)}</i></div>'
        for name, count, amount in period.plans
    )
    return (
        f'<div class="p{" on" if first else ""}" data-k="{period.key}"><div class="g">'
        + _card(period.signups, "ro'yxatdan o'tdi")
        + _card(period.payers, "obuna to'ladi")
        + _card(period.payments, "to'lov")
        + _card(period.amount, "tushum", money=True)
        + "</div>"
        + (f"<h4>Tariflar</h4>{plans}" if plans else "")
        + "</div>"
    )


def render_widget(stats: Stats, *, signups: int, payments: int) -> str:
    tabs = "".join(
        f'<button data-k="{p.key}" class="{"on" if i == 0 else ""}" '
        f"onclick=\"s('{p.key}')\">{_e(p.label)}</button>"
        for i, p in enumerate(stats.periods)
    )
    panels = "".join(_panel(p, i == 0) for i, p in enumerate(stats.periods))
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
        f'<div class="h"><span>TargetologAI · statistika</span><span>{_e(stats.stamp)}</span></div>'
        f'<div class="h"><span>Jami mijoz: {stats.customers}</span>'
        f"<span>Faol obuna: {stats.paying} · sinov: {stats.trial}</span></div>"
        f'<div class="t">{tabs}</div>{panels}'
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


def _t(value: str) -> str:
    """Escaped for a message's HTML, apostrophes left as they are."""
    return escape(value, quote=False)


def render_text(stats: Stats) -> str:
    """The same figures as a message: the caption, and the fallback."""
    lines = [f"<b>📊 Statistika</b> · {_t(stats.stamp)}"]
    for p in stats.periods:
        lines.append(
            f"<b>{_t(p.label)}:</b> {p.signups} ro'yxatdan o'tdi · "
            f"{p.payers} obuna to'ladi · {p.payments} to'lov · {_t(p.amount)}"
        )
    lines.append(
        f"Jami mijoz: {stats.customers} · faol obuna: {stats.paying} · sinov: {stats.trial}"
    )
    return "\n".join(lines)


def render_full_text(stats: Stats) -> str:
    lines = [render_text(stats)]
    if stats.signups:
        lines.append("\n<b>Oxirgi ro'yxatdan o'tganlar:</b>")
        lines += [
            f"{_t(r.when)} — {_t(r.name)}, {_t(r.email)}"
            + (f", {_t(r.phone)}" if r.phone else "")
            for r in stats.signups
        ]
    if stats.paid:
        lines.append("\n<b>Oxirgi to'lovlar:</b>")
        lines += [
            f"{_t(r.email)} — {_t(r.plan)}, "
            f"{_t(format_minor(amount_minor=r.amount_minor, currency=r.currency))}"
            for r in stats.paid
        ]
    return "\n".join(lines)


def send_stats(db: Session, *, client: BotClient, chat_id: str, now: datetime) -> str:
    """The card to one owner's chat; plain text when a widget is refused."""
    stats = read_stats(db, now=now)
    try:
        client.send_widget(
            chat_id=chat_id,
            html=fitted_widget(stats),
            caption=render_text(stats),
            height=WIDGET_HEIGHT,
        )
        return "widget"
    except TelegramTemporaryError:
        raise
    except TelegramError as exc:
        logger.info("admin_stats_widget_refused", extra={"reason": str(exc)})
    client.send_message(chat_id=chat_id, text=render_full_text(stats))
    return "text"


def deliver_admin_report(db: Session, *, now: datetime) -> int:
    """The evening card to every owner; one unreachable chat skips only itself."""
    if not staff_bot_configured() or not settings.staff_bot_admin_ids:
        return 0
    sent = 0
    with staff_bot() as client:
        for chat_id in settings.staff_bot_admin_ids:
            try:
                send_stats(db, client=client, chat_id=chat_id, now=now)
                sent += 1
            except TelegramError as exc:
                logger.warning(
                    "admin_report_failed", extra={"chat": chat_id, "reason": str(exc)}
                )
    return sent


__all__ = [
    "deliver_admin_report",
    "fitted_widget",
    "is_admin",
    "read_stats",
    "render_full_text",
    "send_stats",
]
