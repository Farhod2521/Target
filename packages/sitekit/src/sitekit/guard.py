"""Which addresses this package will open a connection to.

The address is typed by a customer and fetched by our server, so it is a
request made from inside the network on a stranger's behalf. Without this
module ``http://127.0.0.1:5432`` or a cloud metadata address would be a
page like any other.

**Checked on every hop.** A public page may redirect to a private one, so
the check runs before the first request and again before each redirect is
followed - which is why this package follows redirects itself.

**What is left open.** The name is resolved here and again by the HTTP
client, so a DNS server answering differently the second time can still
point the connection somewhere else. The port rule bounds what that
reaches: nothing but 80 and 443 is ever dialled.
"""

import ipaddress
import socket
from collections.abc import Callable, Sequence
from typing import Final

import httpx

ALLOWED_SCHEMES: Final = frozenset({"http", "https"})
ALLOWED_PORTS: Final = frozenset({80, 443})

# ``getaddrinfo`` codes for "this name does not exist", as opposed to "the
# lookup failed". Read by name because the numbers differ between platforms
# and ``EAI_NODATA`` is missing on some.
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
    """Refuse anything but a public web address.

    Every resolved address has to be public, not just one: a name answering
    with a public and a private address is dialled in whichever order the
    client prefers.
    """
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
        # A scoped IPv6 address carries its interface after "%".
        if not ipaddress.ip_address(address.split("%", 1)[0]).is_global:
            raise AddressBlockedError(f"address {address}")


def _literal(host: str) -> list[str]:
    """The host itself when it is already an address, nothing otherwise."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return []
    return [host]
