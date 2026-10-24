"""sitekit - does a web page open, and which advertising tags it carries."""

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
