"""The one way this app reaches Google on a link's behalf."""

from googlekit import SheetsClient, refresh

from app.common.config import settings
from app.common.crypto import decrypt
from app.modules.destinations.models import SheetLink


def open_sheets(*, link: SheetLink) -> SheetsClient:
    """A client holding a fresh access token for ``link``. The caller closes it.

    A refresh every time: it is also the one call that answers whether the
    permission is still there.
    """
    grant = refresh(
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        refresh_token=decrypt(bytes(link.token_encrypted)),
    )
    return SheetsClient(access_token=grant.access_token)
