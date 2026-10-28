"""The waiting list's lines about the accounts that pay for the page."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors.watch import watched_accounts
from app.modules.leads.selectors.reads import uncosted_count
from app.modules.metrics.constants import STALE_HOURS, UNTRACKED_DAYS
from app.modules.metrics.selectors.facts import accounts_stalest_synced_at
from app.modules.notifications.selectors.inbox_page import InboxPage
from core.inbox import InboxItem


def figures_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """Figures that have stopped being refreshed. Silent before the first sync."""
    synced = accounts_stalest_synced_at(db, owner=owner, accounts=view.accounts)
    if synced is None or now - synced <= timedelta(hours=STALE_HOURS):
        return []
    return [
        InboxItem(
            key=f"figures:{synced:%Y-%m-%d}",
            kind="figures",
            level="news",
            title="Raqamlar eskirgan",
            body="Oxirgi yangilanish: %(when)s." % {"when": f"{synced:%d.%m %H:%M}"},
            since=synced,
            action="Yangilash",
            href=reverse("metrics:dashboard"),
        )
    ]


def cap_items(*, view: InboxPage) -> list[InboxItem]:
    """The account has spent up to its own ceiling and stopped."""
    return [
        InboxItem(
            key=f"cap:{account.id}:{account.spend_cap_minor}",
            kind="cap",
            level="urgent",
            title="Akkaunt xarajat chegarasiga yetdi",
            body="Chegara to'ldi - shu sababli reklama ko'rsatilmayapti.",
            since=account.updated_at,
            action="Ko'rish",
            href=reverse("ads:campaigns"),
        )
        for account in view.accounts
        if account.cap_reached
    ]


def unpriced_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """Leads that arrived and whose spend this cabinet cannot see."""
    account = view.home
    if account is None:
        return []

    tzinfo = account.tzinfo()
    today = now.astimezone(tzinfo).date()
    count = uncosted_count(
        db,
        owner=owner,
        since=_moment(today - timedelta(days=UNTRACKED_DAYS - 1), tzinfo=tzinfo),
        until=_moment(today + timedelta(days=1), tzinfo=tzinfo),
        scope=view.shown.leads,
    )
    if not count:
        return []

    watched = watched_accounts(db, owner=owner)
    found = watched[0] if watched else None
    return [
        InboxItem(
            key=f"unpriced:{view.page_id}:{found.external_id if found else ''}:{count}",
            kind="unpriced",
            level="news",
            title="Ba'zi lidlarning xarajati ko'rinmaydi",
            body=_body(count=count, found=found),
            action="Ko'rish",
            href=reverse("leads:sources"),
        )
    ]


def _body(*, count: int, found: AdAccount | None) -> str:
    """The sentence for one of the two cases, named or not."""
    if found is not None:
        return (
            "%(count)d ta lidning xarajati «%(account)s» akkauntidan o'qilyapti. "
            "Bu akkauntni siz tanlamagansiz, lekin reklamangiz undan yuritilyapti - "
            "raqamlar bir kun ichida to'ldiriladi."
        ) % {"count": count, "account": found.name or found.external_id}
    return (
        "%(count)d ta lid siz kuzatmayotgan akkauntdan keldi. Ular «Mijozlar» "
        "bo'limida turibdi, lekin narx hisobiga kirmagan. Reklamani boshqa "
        "kompaniya yuritayotgan bo'lsa, o'sha reklama akkauntiga kirish "
        "huquqini so'rang."
    ) % {"count": count}


def _moment(day: date, *, tzinfo: ZoneInfo) -> datetime:
    """Midnight at the start of a day, in the account's own timezone."""
    return datetime.combine(day, time.min, tzinfo=tzinfo)


__all__ = ["cap_items", "figures_items", "unpriced_items"]
