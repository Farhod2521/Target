"""The waiting list's price rises: one group's result three times its usual price."""

from datetime import datetime
from typing import cast

from adskit import ExternalRef, ProviderName
from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.agent.models import FrequencyAlert, PriceAlert
from app.modules.agent.price_copy import (
    ADD_CREATIVE,
    PAUSE,
    PAUSE_ASKED,
    WATCHING,
    price_body,
    price_title,
)
from app.modules.agent.selectors.price_alerts import (
    merged_frequencies,
    price_alerts_to_show,
)
from app.modules.notifications.selectors.inbox_page import InboxPage
from core.inbox import InboxItem, ItemAction, Subject


def price_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """The page's open price rises, each with its three buttons (TZ 1.5)."""
    rows = price_alerts_to_show(db, owner=owner, hidden_adsets=view.scope.outside)
    merged = merged_frequencies(db, rows=rows)
    return [_item(row, merged.get(row.adset_external_id)) for row in rows]


def price_key(row: PriceAlert) -> str:
    """One rise of one group, the same key the phone claims it under."""
    return f"price:{row.adset_external_id}:{row.id}"


def _item(row: PriceAlert, merged: FrequencyAlert | None) -> InboxItem:
    return InboxItem(
        key=price_key(row),
        kind="price",
        level="urgent",
        title=price_title(row),
        body=price_body(row, frequency=merged),
        since=row.created_at,
        subject=Subject(
            ref=ExternalRef(
                provider=cast("ProviderName", row.provider),
                level="ad" if row.ad_external_id else "adset",
                id=row.ad_external_id or row.adset_external_id,
            ),
            name=row.name,
        ),
        actions=(
            ItemAction(
                label=str(ADD_CREATIVE),
                href=reverse("agent:price_creative", args=[row.id]),
                advised=True,
            ),
            ItemAction(
                label=str(PAUSE),
                href=f"/api/v1/agent/price/{row.id}/pause",
                confirm=PAUSE_ASKED,
            ),
            ItemAction(
                label=str(WATCHING),
                href=f"/api/v1/agent/price/{row.id}/watch",
            ),
        ),
    )


__all__ = ["price_items", "price_key"]
