"""ChatGPT Ads as :class:`adskit.ConnectPort`: an API key, not a consent screen.

OpenAI documents one way in for an advertiser's account: a key the owner
creates in Ads Manager (Settings) and hands over. Each key is scoped to
one ad account, never expires on its own, and is used as it is on every
call. So the browser half of the port has nothing to do and refuses by
name; :meth:`access_token` hands back what was stored.

The OpenAPI document also names an OAuth flow (``auth.openai.com``), but
its clients are issued to OpenAI's partners and how a token picks its
account is not documented. When that changes, it belongs here.
"""

from adskit.dto import GrantDTO
from adskit.errors import InvalidRequest


class KeyConnect:
    """Connection by API key. Holds no configuration: the key is the person's."""

    def authorize_url(self, *, redirect_uri: str, state: str) -> str:
        raise InvalidRequest("ChatGPT Ads connects with an API key, not a redirect")

    def complete(self, *, redirect_uri: str, code: str) -> GrantDTO:
        raise InvalidRequest("ChatGPT Ads connects with an API key, not a redirect")

    def access_token(self, *, stored: str) -> str:
        return stored


__all__ = ["KeyConnect"]
