"""sitekit - does a web page open, and which advertising tags it carries.

No Django, no project imports, no environment. The address is checked
before every request - see :mod:`sitekit.guard` for why that matters when
the address is typed by a customer and fetched by a server.
"""

from sitekit.guard import (
    ALLOWED_PORTS,
    ALLOWED_SCHEMES,
    HostNotFoundError,
    HostUnresolvableError,
    Resolver,
    system_resolver,
)
from sitekit.models import DOWN_FOR_EVERYONE, Outcome, SiteProbe
from sitekit.probe import MAX_BODY_BYTES, MAX_REDIRECTS, USER_AGENT, probe

__all__ = [
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "DOWN_FOR_EVERYONE",
    "MAX_BODY_BYTES",
    "MAX_REDIRECTS",
    "USER_AGENT",
    "HostNotFoundError",
    "HostUnresolvableError",
    "Outcome",
    "Resolver",
    "SiteProbe",
    "probe",
    "system_resolver",
]
