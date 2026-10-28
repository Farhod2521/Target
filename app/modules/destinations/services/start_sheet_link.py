"""The first half of connecting a spreadsheet: where to send the browser."""

import secrets

from googlekit import authorize_url
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.billing.selectors import has_live_subscription
from app.modules.destinations.exceptions import (
    SheetSubscriptionRequired,
    SheetsUnavailable,
)
from app.modules.destinations.selectors import sheets_enabled
from app.modules.destinations.services.choice import SheetChoice, check_choice

STATE_BYTES = 24


def callback_uri(base_url: str) -> str:
    """The redirect URI, the same string on both halves of the handshake."""
    return f"{base_url.rstrip('/')}/api/v1/destinations/google/callback"


def start_sheet_link(
    db: Session, *, user: User, redirect_uri: str, choice: SheetChoice | None
) -> tuple[str, str, SheetChoice | None]:
    """Google's consent URL, the state to remember, and the choice to carry out.

    Every refusal happens here, before the person leaves. ``choice`` is
    ``None`` for the press that mends a stopped link.
    """
    if not sheets_enabled():
        raise SheetsUnavailable
    if not has_live_subscription(db, owner=user):
        raise SheetSubscriptionRequired
    checked = check_choice(db, user=user, choice=choice) if choice is not None else None
    state = secrets.token_urlsafe(STATE_BYTES)
    url = authorize_url(
        client_id=settings.google_oauth_client_id,
        redirect_uri=redirect_uri,
        state=state,
    )
    return url, state, checked


__all__ = ["callback_uri", "start_sheet_link"]
