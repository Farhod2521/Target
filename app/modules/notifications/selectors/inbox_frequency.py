"""The waiting list's frequency lines: one advert seen too often by the same people."""

from datetime import datetime
from typing import Final, cast

from adskit import ExternalRef, ProviderName
from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.agent.constants import FrequencyLevel
from app.modules.agent.frequency_copy import (
    ADD_CREATIVE,
    WORKING_WELL,
    frequency_body,
    frequency_title,
)
from app.modules.agent.models import FrequencyAlert
from app.modules.agent.selectors.frequency import alerts_to_show
from app.modules.notifications.selectors.inbox_page import InboxPage
from core.inbox import InboxItem, ItemAction, Level, Subject

LEVEL_OF: Final[dict[str, Level]] = {
    FrequencyLevel.ADVICE: "news",
    FrequencyLevel.WARNING: "decision",
    FrequencyLevel.REQUIRED: "urgent",
}


def frequency_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """The page's open levels, each with its two buttons - but for one said
    in its group's price rise of the same night (TZ 6.5.6)."""
    from app.modules.agent.selectors.price_alerts import (
        merged_frequencies,
        price_alerts_to_show,
    )

    hidden = view.scope.outside
    prices = price_alerts_to_show(db, owner=owner, hidden_adsets=hidden)
    said = {level.id for level in merged_frequencies(db, rows=prices).values()}
    return [
        _item(row)
        for row in alerts_to_show(db, owner=owner, now=now, hidden_adsets=hidden)
        if row.id not in said
    ]


def frequency_key(row: FrequencyAlert) -> str:
    """One level of one group, the same key the phone claims it under."""
    return f"frequency:{row.adset_external_id}:{row.level}"


def _item(row: FrequencyAlert) -> InboxItem:
    return InboxItem(
        key=frequency_key(row),
        kind="frequency",
        level=LEVEL_OF[row.level],
        title=frequency_title(row),
        body=frequency_body(row),
        since=row.created_at,
        subject=Subject(
            ref=ExternalRef(
                provider=cast("ProviderName", row.provider),
                level="adset",
                id=row.adset_external_id,
            ),
            name=row.name,
        ),
        actions=(
            ItemAction(
                label=str(ADD_CREATIVE),
                href=reverse("agent:frequency_creative", args=[row.id]),
                advised=True,
            ),
            ItemAction(
                label=str(WORKING_WELL),
                # A press the server answers: the API's own path, not a page.
                href=f"/api/v1/agent/frequency/{row.id}/fine",
            ),
        ),
    )


__all__ = ["LEVEL_OF", "frequency_items", "frequency_key"]
