"""The waiting list's line about the night check itself."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.agent.selectors.policy import check_is_late
from core.inbox import InboxItem


def checkup_items(db: Session, *, owner: User, now: datetime) -> list[InboxItem]:
    """The night check not having finished for long enough to say so."""
    since = check_is_late(db, owner=owner, now=now)
    if since is None:
        return []

    days = max(1, (now - since).days)
    return [
        InboxItem(
            key=f"checkup:{since:%Y-%m-%d}",
            kind="checkup",
            level="decision",
            title="Tungi ko'rik o'tmayapti",
            body=(
                "Reklamalaringiz %(days)d kundan beri tekshirilmadi. "
                "Taklif ham, tuzatish ham shundan chiqadi."
            )
            % {"days": days},
            since=since,
            action="Ko'rish",
            href=reverse("agent:history"),
        )
    ]


__all__ = ["checkup_items"]
