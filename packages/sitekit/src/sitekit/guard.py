"""Which addresses this package will open a connection to."""

import ipaddress
import socket
from collections.abc import Callable, Sequence
from typing import Final

import httpx

ALLOWED_SCHEMES: Final = frozenset({"http", "https"})
ALLOWED_PORTS: Final = frozenset({80, 443})

_NOT_FOUND_CODES: Final = frozenset(
    code
    for code in (
        getattr(socket, "EAI_NONAME", None),
        getattr(socket, "EAI_NODATA", None),
    )
    if code is not None
)

type Resolver = Callable[[str, int], Sequence[str]]


class AddressBlockedError(Exception):
    """Not an address this package may open."""


class HostNotFoundError(Exception):
    """The name does not exist. A resolver raises this."""


class HostUnresolvableError(Exception):
    """The name could not be looked up this time. A resolver raises this."""


def system_resolver(host: str, port: int) -> list[str]:
    """Every address the operating system gives for ``host``."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        if exc.errno in _NOT_FOUND_CODES:
            raise HostNotFoundError(host) from exc
        raise HostUnresolvableError(host) from exc
    return sorted({str(info[4][0]) for info in infos})


def check_address(url: httpx.URL, *, resolve: Resolver) -> None:
    """Refuse anything but a public web address."""
    if url.scheme not in ALLOWED_SCHEMES:
        raise AddressBlockedError(f"scheme {url.scheme!r}")
    port = url.port or (443 if url.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise AddressBlockedError(f"port {port}")
    host = url.host
    if not host:
        raise AddressBlockedError("no host")

    addresses = _literal(host) or list(resolve(host, port))
    if not addresses:
        raise HostNotFoundError(host)
    for address in addresses:
        if not ipaddress.ip_address(address.split("%", 1)[0]).is_global:
            raise AddressBlockedError(f"address {address}")


def _literal(host: str) -> list[str]:
    """The host itself when it is already an address, nothing otherwise."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return []
    return [host]
