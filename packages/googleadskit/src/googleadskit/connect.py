"""Google as :class:`adskit.ConnectPort`: consent, code, refresh token.

Google's sign-in is not Google Ads' own - it is the same OAuth every Google
API uses - so the four calls live in ``googlekit`` and this class only
decides what to ask for and what to keep.

**What is stored is the refresh token.** An access token lives an hour, so
keeping one would leave a connection that dies by lunchtime. The refresh
token lasts until the person withdraws it, and :meth:`access_token` trades
it for an hour's access before every piece of work.

**The person is named by ``sub``**, Google's permanent id, not the email:
an address can change, and the rule it serves - one Google account, one
cabinet - must not be escaped by renaming one.
"""

from typing import Final

from adskit.dto import GrantDTO
from adskit.errors import (
    AuthFailed,
    InvalidRequest,
    PermissionDenied,
    ProviderError,
    TemporaryFailure,
)
from googlekit import (
    SCOPE_ADWORDS,
    AccessRevoked,
    GoogleError,
    PermissionMissing,
    Unavailable,
    authorize_url,
    exchange_code,
    refresh,
)

# Who the person is, and their Google Ads. Nothing about Drive: a grant
# asks for what this connection uses and no more.
SCOPES: Final = ("openid", "email", SCOPE_ADWORDS)


class GoogleConnect:
    """The OAuth client's id and secret, given once, used for every person."""

    def __init__(self, *, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    def authorize_url(self, *, redirect_uri: str, state: str) -> str:
        return authorize_url(
            client_id=self._client_id,
            redirect_uri=redirect_uri,
            state=state,
            scopes=SCOPES,
        )

    def complete(self, *, redirect_uri: str, code: str) -> GrantDTO:
        try:
            grant = exchange_code(
                client_id=self._client_id,
                client_secret=self._client_secret,
                redirect_uri=redirect_uri,
                code=code,
            )
        except GoogleError as exc:
            raise _translate(exc) from exc
        if not grant.refresh_token:
            # ``prompt=consent`` makes Google send one every time; without
            # it there is nothing that outlives the hour.
            raise InvalidRequest("Google answered without a refresh token")
        return GrantDTO(
            token=grant.refresh_token,
            scopes=grant.scopes,
            external_user_id=grant.subject,
        )

    def access_token(self, *, stored: str) -> str:
        try:
            grant = refresh(
                client_id=self._client_id,
                client_secret=self._client_secret,
                refresh_token=stored,
            )
        except GoogleError as exc:
            raise _translate(exc) from exc
        return grant.access_token


def _translate(exc: GoogleError) -> ProviderError:
    """A sign-in failure in the domain's words."""
    if isinstance(exc, AccessRevoked):
        return AuthFailed(str(exc), code="access_revoked")
    if isinstance(exc, PermissionMissing):
        return PermissionDenied(str(exc), code="permission_missing")
    if isinstance(exc, Unavailable):
        return TemporaryFailure(str(exc), code="unavailable")
    return InvalidRequest(str(exc), code="oauth")


__all__ = ["SCOPES", "GoogleConnect"]
