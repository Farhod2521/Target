"""Meta's ``signed_request``: the payload behind the Data Deletion callback.

Pure functions, no Django. This is the security boundary of a public,
CSRF-exempt endpoint, so it has to be testable without a database, a request
object or a settings module - the app secret arrives as an argument.

The wire format is ``<signature>.<payload>``, both base64url without padding.
The signature is HMAC-SHA256 over the *encoded* payload string exactly as it
arrived, never over the re-serialised JSON: whitespace and key order would
differ and the digest with them.
"""

import base64
import binascii
import hmac
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Final

# The only algorithm Meta signs deletion callbacks with. A payload naming
# anything else is refused rather than trusted: an attacker who can choose
# the algorithm can choose a weak one.
SUPPORTED_ALGORITHM: Final = "HMAC-SHA256"

SEPARATOR: Final = "."


class SignedRequestError(Exception):
    """The payload cannot be trusted. Every cause maps to HTTP 400.

    Deliberately one class: telling a caller *which* check failed tells an
    attacker how far their forgery got.
    """


@dataclass(frozen=True, slots=True)
class SignedRequest:
    """A verified callback payload.

    Only exists once the signature checked out, so holding one is proof the
    request came from Meta. ``issued_at`` is Meta's Unix timestamp and may be
    absent; the caller stamps its own clock rather than trusting this one.
    """

    user_id: str
    algorithm: str
    issued_at: int | None


def _decode_base64url(value: str) -> bytes:
    """Decode base64url, restoring the padding Meta strips."""
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (binascii.Error, ValueError) as exc:
        raise SignedRequestError("signed_request is not valid base64url") from exc


def _decode_payload(encoded: str) -> dict[str, Any]:
    """Read the JSON body of a signed request."""
    try:
        payload = json.loads(_decode_base64url(encoded))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SignedRequestError("signed_request payload is not JSON") from exc
    if not isinstance(payload, dict):
        raise SignedRequestError("signed_request payload is not an object")
    return payload


def parse_signed_request(raw: str, *, app_secret: str) -> SignedRequest:
    """Verify the signature and return the payload.

    Raises :class:`SignedRequestError` on anything short of a valid, correctly
    signed payload carrying a ``user_id``.

    ``app_secret`` must not be empty. An empty key still produces a perfectly
    valid HMAC, so a misconfigured deployment would accept forged callbacks
    from anyone who guessed the secret was unset - which is why this is
    checked here as well as at the call site.
    """
    if not app_secret:
        raise SignedRequestError("app secret is not configured")
    if not raw:
        raise SignedRequestError("signed_request is empty")

    encoded_signature, separator, encoded_payload = raw.partition(SEPARATOR)
    if not separator or not encoded_signature or not encoded_payload:
        raise SignedRequestError("signed_request is not in <signature>.<payload> form")

    # base64url is an ASCII alphabet by definition, so anything else is not a
    # signed request at all - and .encode() below would raise rather than fail
    # the comparison cleanly.
    if not encoded_payload.isascii():
        raise SignedRequestError("signed_request payload is not base64url")

    signature = _decode_base64url(encoded_signature)
    expected = hmac.new(
        app_secret.encode("utf-8"),
        # The encoded payload, byte for byte as received.
        encoded_payload.encode("ascii"),
        sha256,
    ).digest()

    # Constant time: a byte-by-byte comparison leaks the correct prefix and
    # turns forgery into 32 cheap guesses instead of one impossible one.
    if not hmac.compare_digest(signature, expected):
        raise SignedRequestError("signed_request signature does not match")

    payload = _decode_payload(encoded_payload)

    algorithm = payload.get("algorithm")
    if not isinstance(algorithm, str) or algorithm.upper() != SUPPORTED_ALGORITHM:
        raise SignedRequestError("signed_request algorithm is not supported")

    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise SignedRequestError("signed_request carries no user_id")

    issued_at = payload.get("issued_at")
    if not isinstance(issued_at, int) or isinstance(issued_at, bool):
        issued_at = None

    return SignedRequest(user_id=user_id, algorithm=algorithm, issued_at=issued_at)


def build_signed_request(payload: dict[str, Any], *, app_secret: str) -> str:
    """Sign a payload the way Meta does.

    Exists for the tests: a fixture that hardcodes a signature would only
    prove the digest was copied correctly, not that verification works.
    """
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(body).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        app_secret.encode("utf-8"), encoded_payload.encode("ascii"), sha256
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{encoded_signature}{SEPARATOR}{encoded_payload}"
