"""Getting a token, and finding out what is left of one."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Final
from urllib.parse import urlencode

from metaads.client import OAUTH_DIALOG_URL, GraphClient
from metaads.dto import AccessTokenDTO, PersonDTO, TokenInfoDTO
from metaads.parsing import parsed

REQUIRED_SCOPES: Final = (
    "ads_management",
    "ads_read",
    "business_management",
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_metadata",
    "pages_manage_ads",
    "leads_retrieval",
)

INSTAGRAM_SCOPE: Final = "instagram_basic"

OPTIONAL_SCOPES: Final = (INSTAGRAM_SCOPE,)

DEFAULT_SCOPES: Final = REQUIRED_SCOPES + OPTIONAL_SCOPES


def authorize_url(
    *,
    app_id: str,
    redirect_uri: str,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> str:
    """Where to send the browser."""
    query = urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(scopes),
            "response_type": "code",
            "auth_type": "rerequest",
        }
    )
    return f"{OAUTH_DIALOG_URL}?{query}"


def exchange_code(
    *,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
    code: str,
    client: GraphClient | None = None,
) -> AccessTokenDTO:
    """Trade the callback's code for a short-lived token."""
    with _session(client) as graph:
        payload = graph.get(
            "oauth/access_token",
            client_id=app_id,
            client_secret=app_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
    return parsed(AccessTokenDTO, payload)


def exchange_for_long_lived(
    *,
    app_id: str,
    app_secret: str,
    token: str,
    client: GraphClient | None = None,
) -> AccessTokenDTO:
    """Turn an hour into about sixty days."""
    with _session(client) as graph:
        payload = graph.get(
            "oauth/access_token",
            grant_type="fb_exchange_token",
            client_id=app_id,
            client_secret=app_secret,
            fb_exchange_token=token,
        )
    return parsed(AccessTokenDTO, payload)


def inspect_token(
    *,
    app_id: str,
    app_secret: str,
    token: str,
    client: GraphClient | None = None,
) -> TokenInfoDTO:
    """Ask Meta what this token still is."""
    with _session(client) as graph:
        payload = graph.get(
            "debug_token",
            input_token=token,
            access_token=f"{app_id}|{app_secret}",
        )
    return parsed(TokenInfoDTO, payload.get("data", {}))


def describe_person(*, token: str, client: GraphClient | None = None) -> PersonDTO:
    """Whose token this is, by the name they go by on Facebook."""
    with _session(client) as graph:
        payload = graph.get("me", fields="id,name", access_token=token)
    return parsed(PersonDTO, payload)


def revoke_access(
    *,
    user_id: str,
    token: str,
    client: GraphClient | None = None,
) -> bool:
    """Hand every permission back and unlink the app from this person."""
    with _session(client) as graph:
        payload = graph.delete(f"{user_id}/permissions", access_token=token)
    return bool(payload.get("success", False))


@contextmanager
def _session(client: GraphClient | None) -> Iterator[GraphClient]:
    """A client for one exchange, closing only what it opened."""
    if client is not None:
        yield client
        return

    graph = GraphClient()
    try:
        yield graph
    finally:
        graph.close()


def missing(
    granted: Sequence[str], *, required: Sequence[str] = REQUIRED_SCOPES
) -> tuple[str, ...]:
    """Which required permissions this token does not carry."""
    if not granted:
        return ()
    held = {scope.strip() for scope in granted if scope.strip()}
    return tuple(scope for scope in required if scope not in held)


def holds(granted: Sequence[str], scope: str) -> bool:
    """Whether this token carries one particular permission."""
    if not granted:
        return True
    return scope in {held.strip() for held in granted if held.strip()}
