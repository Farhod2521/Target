"""Getting a token, and finding out what is left of one.

Four steps, in the order they happen: send the person to Meta, trade the
code they come back with for a token, trade that short-lived token for a
long-lived one, and afterwards ask Meta periodically whether it still
works.

The third step is not optional. The token a code buys lasts about an hour;
the one it is exchanged for lasts about sixty days. Skipping the exchange
produces a connection that works for the rest of the afternoon and is dead
by morning, which is the kind of bug that gets diagnosed twice.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Final
from urllib.parse import urlencode

from metaads.client import OAUTH_DIALOG_URL, GraphClient
from metaads.dto import AccessTokenDTO, PersonDTO, TokenInfoDTO
from metaads.parsing import parsed

# Everything the product needs, asked for once.
#
# Asking twice is what a staged approach costs: a person who granted ads
# access in March and is asked again in May for leads reads the second
# prompt as the first one not having worked. One prompt is also one App
# Review submission.
#
#   ads_management         create and change campaigns
#   ads_read               read them and their performance
#   business_management    reach accounts owned by a Business Manager
#   pages_show_list        list the pages they administer
#   pages_read_engagement  read a page's own details
#   pages_manage_metadata  subscribe a page to lead webhooks
#   pages_manage_ads       create a lead form on a page
#   leads_retrieval        read the leads a form collected
#
# ``pages_manage_ads`` is the one whose absence stays invisible until the
# fifth call of a creation sequence: Meta answers ``POST
# /{page_id}/leadgen_forms`` with "#200 requires pages_manage_ads", which
# names the permission but not the fact that it was never asked for. A page
# token inherits the user token's grants, so without it the form cannot be
# created by anybody.
#
# Adding one is a breaking change for tokens already issued: they carry
# what was asked for on the day they were made, and only reconnecting
# widens them. See ``missing`` below - it is what turns that into a
# sentence instead of a refusal five calls deep.
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

# Asked for on the same screen and **never required by a launch**.
#
#   instagram_basic        read the page's Instagram account and its media
#
# The split is the whole point of this pair, and collapsing it would be an
# outage. ``missing`` is what refuses a campaign, and it is read by
# the launch gate, the preflight check and the readiness screen; everything
# it names has to be something the creation sequence genuinely cannot run
# without. ``instagram_basic`` is not - it fills a picker with the pictures
# somebody already posted, and an advertiser who unticked the box, or who
# connected before it was ever asked for, should lose that grid and nothing
# else.
#
# Putting it in ``REQUIRED_SCOPES`` instead would refuse every launch on
# every connection made before it was asked for, for a permission no
# launch uses.
INSTAGRAM_SCOPE: Final = "instagram_basic"

OPTIONAL_SCOPES: Final = (INSTAGRAM_SCOPE,)

# What the consent dialog asks for: both lists, once. Asking twice is what
# a staged approach costs - see above.
DEFAULT_SCOPES: Final = REQUIRED_SCOPES + OPTIONAL_SCOPES


def authorize_url(
    *,
    app_id: str,
    redirect_uri: str,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> str:
    """Where to send the browser.

    ``state`` is not decoration. It is the only thing tying the callback to
    the session that started it; without it anyone can hand a signed-in
    victim a callback URL and attach their own Meta account to that
    victim's cabinet. The caller generates it, stores it in the session,
    and compares on the way back.

    ``auth_type=rerequest`` on every visit, not only on a reconnect. Once
    somebody has unticked a permission, Meta's dialog will not ask for it
    again unless told it is being asked again - so without this, the
    "Qayta ulash" button offered to somebody missing ``instagram_basic``
    walks them through the whole dialog and hands back the same token.
    On a first visit nothing has been declined and the parameter changes
    nothing, which is why it is not a flag.
    """
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
    """Trade the callback's code for a short-lived token.

    ``redirect_uri`` has to match the one used to build the dialog URL
    exactly, including the trailing slash. Meta compares strings, and the
    error it returns when they differ says nothing about which one it
    disliked.
    """
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
    """Turn an hour into about sixty days.

    Also how a token is renewed: exchanging a long-lived token that is
    still valid returns a fresh sixty days. There is no refresh token to
    hold - the current token is the refresh token, which is why letting one
    expire cannot be undone without the person coming back.
    """
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
    """Ask Meta what this token still is.

    The authoritative answer to "is it valid, whose is it, what may it do
    and when does it die". Checked on a schedule rather than assumed from
    the moment of issue, because a person can revoke access in their
    Facebook settings and nothing tells us.

    Authenticated with the app token - ``{id}|{secret}`` - because a dead
    user token cannot be used to ask about itself.
    """
    with _session(client) as graph:
        payload = graph.get(
            "debug_token",
            input_token=token,
            access_token=f"{app_id}|{app_secret}",
        )
    return parsed(TokenInfoDTO, payload.get("data", {}))


def describe_person(*, token: str, client: GraphClient | None = None) -> PersonDTO:
    """Whose token this is, by the name they go by on Facebook.

    Asked with the token itself rather than the app's. ``debug_token``
    already says whose it is, but only by id - and the one place the name
    is needed is a sentence telling somebody which profile to sign in
    with, where a number is no help.

    ``name`` comes with the default ``public_profile`` grant, so nothing new
    is asked for on the consent screen.
    """
    with _session(client) as graph:
        payload = graph.get("me", fields="id,name", access_token=token)
    return parsed(PersonDTO, payload)


def revoke_access(
    *,
    user_id: str,
    token: str,
    client: GraphClient | None = None,
) -> bool:
    """Hand every permission back and unlink the app from this person.

    ``DELETE /{user-id}/permissions`` with no ``permission`` named removes
    all of them at once, which is what erasing somebody means: not a token
    we stop using, but an app that no longer appears in their Facebook
    settings and cannot be handed a new token without them going through
    consent again.

    Returns whether Meta agreed. A ``False`` is worth recording and is not
    worth stopping for - the token is about to be destroyed on our side
    either way, and a permission left dangling on an account we can no
    longer reach is a smaller problem than a deletion that refused to run
    because Meta was slow.

    Meta answers this by posting a deletion callback of its own. Handling
    that is the caller's problem, and the callback path already treats a
    person it cannot find as a request to record rather than an error.
    """
    with _session(client) as graph:
        payload = graph.delete(f"{user_id}/permissions", access_token=token)
    return bool(payload.get("success", False))


@contextmanager
def _session(client: GraphClient | None) -> Iterator[GraphClient]:
    """A client for one exchange, closing only what it opened.

    A caller-supplied client is handed back untouched: closing somebody
    else's connection pool because we borrowed it for one call is the kind
    of surprise that shows up as an unrelated timeout later.
    """
    if client is not None:
        yield client
        return

    # Token-less: every call in this module carries its own credentials as
    # parameters rather than as a bearer token.
    graph = GraphClient()
    try:
        yield graph
    finally:
        graph.close()


def missing(
    granted: Sequence[str], *, required: Sequence[str] = REQUIRED_SCOPES
) -> tuple[str, ...]:
    """Which required permissions this token does not carry.

    ``REQUIRED_SCOPES`` and not ``DEFAULT_SCOPES``, which is the difference
    between a narrow token and a refused campaign. Every caller of this
    function turns a non-empty answer into a blocked launch, so an optional
    permission listed here would take the button away from everybody who
    connected before it was asked for - see ``OPTIONAL_SCOPES``.

    An empty ``granted`` means "nobody has asked Meta yet", not "nothing
    was granted", and returns nothing. The distinction matters: a token
    whose scopes were never recorded carries no list here, and treating
    that as a failure would lock out every connection that already works.
    """
    if not granted:
        return ()
    held = {scope.strip() for scope in granted if scope.strip()}
    return tuple(scope for scope in required if scope not in held)


def holds(granted: Sequence[str], scope: str) -> bool:
    """Whether this token carries one particular permission.

    For the optional half, where the question is not "may this launch run"
    but "is this screen worth drawing". A separate function rather than
    ``scope not in missing(...)`` because the two answers are read in
    opposite directions and one of them is about a refusal.

    Unknown counts as held, for the reason :func:`missing` returns nothing
    for an empty list: a connection whose scopes were never recorded is one
    Meta has not been asked about, and the honest cost of guessing wrong
    here is a provider call that fails and is logged - not a screen taken
    away from somebody who has the permission.
    """
    if not granted:
        return True
    return scope in {held.strip() for held in granted if held.strip()}
