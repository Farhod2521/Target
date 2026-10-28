"""Everything one cabinet is waiting on, gathered from the modules that own it.

No table behind it: each item already exists somewhere a reader can open, and
this asks all of them at once. A mended thing simply stops being in the list.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.ads.constants import LaunchStatus
from app.modules.ads.selectors.launches import refused_launch, resume_step
from app.modules.agent.constants import (
    FIX_LABELS,
    FIX_NEWS_DAYS,
    FIX_REASONS,
    FIXES_IN_LIST,
    RULE_LABELS,
    SuggestionKind,
)
from app.modules.agent.models import AgentFix
from app.modules.agent.selectors.suggestions import waiting
from app.modules.billing.selectors.subscription import live_subscription
from app.modules.integrations.models import PageAccount
from app.modules.leads.selectors.reads import delivery_trouble
from app.modules.notifications.selectors.inbox_accounts import (
    figures_items,
    unpriced_items,
)
from app.modules.notifications.selectors.inbox_agent import checkup_items
from app.modules.notifications.selectors.inbox_cabinet import cabinet_items
from app.modules.notifications.selectors.inbox_diagnoses import diagnosis_items
from app.modules.notifications.selectors.inbox_frequency import frequency_items
from app.modules.notifications.selectors.inbox_leads import (
    lead_gap_items,
    stuck_sweep_items,
    unheard_page_items,
)
from app.modules.notifications.selectors.inbox_meta import meta_items
from app.modules.notifications.selectors.inbox_notes import (
    advice_items,
    ranking_items,
    refusal_items,
)
from app.modules.notifications.selectors.inbox_page import InboxPage, inbox_page
from app.modules.notifications.selectors.inbox_spend import quiet_waits
from app.modules.notifications.selectors.inbox_stops import stop_items
from app.modules.notifications.selectors.inbox_watch import watch_items
from core.inbox import InboxItem, Subject, ordered

# The launch states that mean something was refused halfway.
BROKEN_LAUNCHES = (LaunchStatus.FAILED, LaunchStatus.ROLLED_BACK)


def inbox(db: Session, *, owner: User, now: datetime) -> tuple[InboxItem, ...]:
    """Everything waiting for this owner on the page they are on, worst first."""
    return ordered(
        [
            *cabinet_inbox(db, owner=owner, now=now),
            *page_inbox(db, owner=owner, view=inbox_page(db, owner=owner), now=now),
        ]
    )


def cabinet_inbox(db: Session, *, owner: User, now: datetime) -> tuple[InboxItem, ...]:
    """The lines that belong to no page: the whole cabinet's own."""
    live = live_subscription(db, owner=owner)
    return (
        *cabinet_items(db, owner=owner, live=live, now=now),
        *checkup_items(db, owner=owner, now=now),
    )


def page_inbox(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> tuple[InboxItem, ...]:
    """Everything waiting on one page, worst first. The only list of sources."""
    return ordered(
        quiet_waits(
            [
                *_suggestions(db, owner=owner, view=view, now=now),
                *stop_items(db, owner=owner, view=view),
                *meta_items(db, owner=owner, accounts=view.accounts),
                *watch_items(db, owner=owner, view=view, now=now),
                *frequency_items(db, owner=owner, view=view, now=now),
                *refusal_items(db, owner=owner, view=view, now=now),
                *_launch(db, owner=owner, view=view),
                *figures_items(db, owner=owner, view=view, now=now),
                *_leads(db, owner=owner, view=view, now=now),
                *lead_gap_items(db, owner=owner, view=view, now=now),
                *unheard_page_items(db, owner=owner, view=view, now=now),
                *stuck_sweep_items(db, owner=owner, page=view.page, now=now),
                *unpriced_items(db, owner=owner, view=view, now=now),
                *ranking_items(db, owner=owner, view=view, now=now),
                *advice_items(db, owner=owner, view=view),
                *diagnosis_items(db, owner=owner, view=view, now=now),
                *_repairs(db, owner=owner, view=view, now=now),
            ]
        )
    )


def _repairs(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """What the agent put right by itself this week. A repair to another page is its news."""
    other_pages = select(PageAccount.external_id).where(
        PageAccount.owner_id == owner.id,
        PageAccount.external_id != view.scope.current,
    )
    rows = db.scalars(
        select(AgentFix)
        .where(
            AgentFix.owner_id == owner.id,
            AgentFix.created_at >= now - timedelta(days=FIX_NEWS_DAYS),
            AgentFix.target_id.not_in(other_pages),
        )
        .order_by(AgentFix.created_at.desc())
        .limit(FIXES_IN_LIST)
    )
    return [
        InboxItem(
            key=f"repair:{row.id}",
            kind="repair",
            level="news",
            title=FIX_LABELS.get(row.action, "Tuzatildi"),
            body=FIX_REASONS.get(row.action, ""),
            since=row.created_at,
            action="AI dan so'rash",
            href=f"{reverse('chat:chat')}?item=repair:{row.id}",
        )
        for row in rows
    ]


def _suggestions(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """Open proposals, one line each. Answered where they are drawn: no button here."""
    return [
        InboxItem(
            key=f"suggestion:{row.id}",
            kind="suggestion",
            level="decision",
            title=SuggestionKind(row.kind).label,
            body=str(RULE_LABELS.get(row.rule, "")),
            since=row.created_at,
            subject=Subject(ref=row.to_ref()),
        )
        for row in waiting(db, owner=owner, now=now, scope=view.scope)
    ]


def _launch(db: Session, *, owner: User, view: InboxPage) -> list[InboxItem]:
    """A campaign the provider refused on this page, if there is one."""
    if view.page is None:
        return []
    launch = refused_launch(db, owner=owner, page=view.page)
    if launch is None or launch.status not in BROKEN_LAUNCHES:
        return []
    return [
        InboxItem(
            key=f"launch:{launch.id}:{launch.status}",
            kind="launch",
            level="urgent",
            title="Reklama yaratilmadi",
            body="Javoblaringiz saqlangan - qaytib davom ettirish mumkin.",
            since=launch.updated_at,
            action="Davom ettirish",
            href=reverse(f"ads:launch_{resume_step(launch)}", args=[launch.id]),
        )
    ]


def _leads(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """Enquiries that were paid for and never arrived, while they can still be fetched."""
    lost = delivery_trouble(
        db, owner=owner, now=now, scope=view.shown.deliveries
    ).recoverable
    if not lost:
        return []
    return [
        InboxItem(
            key=f"leads:{view.page_id}:{lost}",
            kind="leads",
            level="news",
            title="Yig'ilmagan mijozlar bor",
            body="%(count)d ta murojaatni hali tiklash mumkin." % {"count": lost},
            action="Ko'rish",
            href=reverse("leads:sources"),
        )
    ]


__all__ = ["cabinet_inbox", "inbox", "page_inbox"]
