"""The owners' figures in Telegram: who signed up, who paid, how much, and
what the platform and the office are doing.

Who is an owner here is ``STAFF_BOT_ADMIN_IDS`` - Telegram user ids, set on
the server, not an office role and not a linked cabinet: the card carries
every customer's name and the money. It goes out only through the owners'
own bot (``OWNERS_BOT_TOKEN``, @owners_tai_bot), every morning at 07:00
Tashkent time and on ``/admin`` there (``owners_respond``); the customers'
and the office's bots no longer show it. The
first column is yesterday - at seven in the morning today has barely begun.

The card is a picture: the designed card (``assets/admin_card.png``) with
the figures written into it by ``admin_card``, sent as a photo with no
caption - the picture says it all - and the office button under it. Telegram's in-message HTML widgets (Bot API
10.4) would have been the first choice, but Telegram closed them to
ordinary bots on 13 November 2026 (``INPUT_MEDIA_WIDGET_NOT_ALLOWED``).
When the picture cannot be sent, the same figures go as plain text. The
figures are the office dashboard's own selectors, so the two never
disagree.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from telegramkit import (
    BotClient,
    Button,
    TelegramError,
    TelegramTemporaryError,
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
from app.modules.notifications.bot import owners_bot, owners_bot_configured

logger = logging.getLogger(__name__)

YESTERDAY: Final = "yesterday"
PERIODS: Final = ((YESTERDAY, "Kecha"), ("7", "7 kun"), ("30", "30 kun"))
SIGNUPS_SHOWN: Final = 7
PAYMENTS_SHOWN: Final = 5


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
        if key == YESTERDAY:
            day = today - timedelta(days=1)
            window = asked_window(period="range", since=day, until=day, today=today)
        else:
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


# -- the text --------------------------------------------------------------------


def _t(value: str) -> str:
    """Escaped for a message's HTML, apostrophes left as they are."""
    return escape(value, quote=False)


def render_full_text(stats: Stats) -> str:
    """Everything the card shows, for when the picture cannot be sent."""
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
    """The card to one owner's chat; plain text when the picture fails."""
    from app.modules.notifications.services.admin_card import draw_card

    stats = read_stats(db, now=now)
    try:
        client.send_photo(
            chat_id=chat_id,
            filename="statistika.jpg",
            content=draw_card(stats),
            buttons=_office_button(),
        )
        return "card"
    except TelegramTemporaryError:
        raise
    except (TelegramError, OSError, ValueError) as exc:
        logger.warning("admin_stats_card_failed: %s", exc)
    client.send_message(
        chat_id=chat_id, text=render_full_text(stats), buttons=_office_button()
    )
    return "text"


def deliver_admin_report(db: Session, *, now: datetime) -> int:
    """The morning card to every owner; one unreachable chat skips only itself.
    An owner who never pressed Start in @owners_tai_bot cannot be written to."""
    if not (settings.staff_bot_admin_ids and owners_bot_configured()):
        return 0
    sent = 0
    with owners_bot() as client:
        for chat_id in settings.staff_bot_admin_ids:
            try:
                send_stats(db, client=client, chat_id=chat_id, now=now)
                sent += 1
            except TelegramError as exc:
                logger.warning("admin_report_failed for %s: %s", chat_id, exc)
    return sent


__all__ = [
    "deliver_admin_report",
    "is_admin",
    "read_stats",
    "render_full_text",
    "send_stats",
]
