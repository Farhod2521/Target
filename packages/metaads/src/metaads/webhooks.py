"""The other direction: Meta calling us when a form is filled in.

Pure functions, no Django. This is the security boundary of a public,
unauthenticated, CSRF-exempt endpoint - the same shape as
:mod:`metaads.signed_request` and for the same reasons - so it has to be
testable without a request object, a database or a settings module. Both
secrets arrive as arguments.

Two things arrive here and they are unrelated:

**The verification handshake.** Meta calls the URL once with ``GET`` when
the subscription is set up, carrying a token the developer chose. Echo the
challenge back and the webhook is registered; get it wrong and it is not,
with no other symptom.

**The notification.** A ``POST`` signed with ``X-Hub-Signature-256``, whose
body says only that a lead exists - never what is in it. The lead itself is
a second call, which is why nothing here fetches anything: the caller
stores this first and asks Meta afterwards, so that Meta being slow costs a
retry rather than the lead.

One POST can carry several pages and several leads. Meta batches, and a
handler written for a single lead silently drops the rest of a busy minute.
"""

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Final

# The prefix Meta puts in front of the hex digest. Split off rather than
# stripped blindly: a header naming a different algorithm is refused, since
# an attacker who chooses the algorithm can choose a weak one.
SIGNATURE_PREFIX: Final = "sha256="

# What the handshake sends. ``subscribe`` is the only mode Meta uses for
# this; anything else is not a handshake and is not answered.
SUBSCRIBE_MODE: Final = "subscribe"

# The only webhook field this product asks for, and therefore the only one
# it acts on. A payload carrying something else is somebody else's
# subscription arriving on our URL.
LEADGEN_FIELD: Final = "leadgen"

# Meta's own word for the top-level object. Page webhooks say "page"; an
# app-level or instagram subscription says something else and is ignored
# rather than half-parsed.
PAGE_OBJECT: Final = "page"


@dataclass(frozen=True, slots=True)
class LeadNotice:
    """One "a form was filled in" from Meta. Not the lead.

    Every field is an id and none of them is the answer sheet - Meta never
    puts personal data in a webhook body. ``leadgen_external_id`` is what
    the second call asks for, and ``page_external_id`` is what says whose
    lead this is, because a webhook arrives with no owner attached.

    ``created_at`` is when the person pressed submit, as Meta timed it.
    Carried because the fetch may happen minutes later and "when did this
    lead arrive" must not become "when did our worker get to it".
    """

    page_external_id: str
    leadgen_external_id: str
    form_external_id: str = ""
    ad_external_id: str = ""
    adset_external_id: str = ""
    created_at: datetime | None = None


def verify_signature(*, body: bytes, header: str, app_secret: str) -> bool:
    """Whether this body really came from Meta.

    Over the **raw bytes exactly as they arrived**, never over re-serialised
    JSON: key order and whitespace would differ and the digest with them.
    That is the single easiest way to write a signature check that rejects
    every genuine request.

    Compared with :func:`hmac.compare_digest`, which takes the same time
    whether the first byte differs or the last.

    Returns a boolean rather than raising, because the caller stores the
    payload either way. A rejected signature is evidence worth keeping: a
    run of them is either an attacker or an app secret that was rotated
    without telling this deployment.
    """
    if not app_secret or not header.startswith(SIGNATURE_PREFIX):
        return False

    expected = hmac.new(app_secret.encode(), body, sha256).hexdigest()
    return hmac.compare_digest(header[len(SIGNATURE_PREFIX) :].strip(), expected)


def verification_challenge(
    *, mode: str, token: str, challenge: str, expected_token: str
) -> str:
    """The answer to Meta's setup handshake, or an empty string.

    Empty means "do not echo": the caller answers 403 and the subscription
    is not created. Silence is the correct response to a wrong token - a
    body explaining what was wrong would tell whoever guessed how close
    they got.

    The token is compared in constant time even though it is not a
    signature. It is a shared secret and there is no reason to leak its
    length one byte at a time.
    """
    if mode != SUBSCRIBE_MODE or not expected_token:
        return ""
    if not hmac.compare_digest(token, expected_token):
        return ""
    return challenge


def leadgen_notices(payload: dict[str, Any]) -> tuple[LeadNotice, ...]:
    """Every lead named in one delivery, in the order Meta listed them.

    Batched on both axes: several pages per delivery and several changes
    per page. A handler written for one lead drops the rest of a busy
    minute, and there is nothing anywhere to say that it did.

    Anything that is not a leadgen change on a page object is skipped
    rather than refused. Meta delivers whatever the app is subscribed to
    down one URL, and a webhook this product did not ask for is not an
    error - it is somebody else's feature arriving early.
    """
    if payload.get("object") != PAGE_OBJECT:
        return ()

    entries = payload.get("entry")
    if not isinstance(entries, list):
        return ()

    notices: list[LeadNotice] = []
    for entry in entries:
        if isinstance(entry, dict):
            notices.extend(_from_entry(entry))
    return tuple(notices)


def _from_entry(entry: dict[str, Any]) -> list[LeadNotice]:
    """The leads named under one page."""
    changes = entry.get("changes")
    if not isinstance(changes, list):
        return []

    found: list[LeadNotice] = []
    for change in changes:
        if not isinstance(change, dict) or change.get("field") != LEADGEN_FIELD:
            continue
        value = change.get("value")
        if not isinstance(value, dict):
            continue
        notice = _from_value(value, fallback_page=str(entry.get("id", "")))
        if notice is not None:
            found.append(notice)
    return found


def _from_value(value: dict[str, Any], *, fallback_page: str) -> LeadNotice | None:
    """One change, or None when it names no lead.

    A notice without a ``leadgen_id`` is unusable: it is the only field the
    second call needs, and storing a row that can never be resolved would
    put a permanent failure in a table that is retried.

    The page id falls back to the entry's own, because Meta puts it in both
    places and has been known to omit it from the inner one.
    """
    leadgen_id = str(value.get("leadgen_id", "")).strip()
    if not leadgen_id:
        return None

    return LeadNotice(
        page_external_id=str(value.get("page_id", "")).strip() or fallback_page,
        leadgen_external_id=leadgen_id,
        form_external_id=str(value.get("form_id", "")).strip(),
        ad_external_id=str(value.get("ad_id", "")).strip(),
        # ``adgroup_id`` here and ``adset_id`` on the Graph read. Meta's own
        # inconsistency, and both are accepted.
        adset_external_id=str(
            value.get("adgroup_id") or value.get("adset_id") or ""
        ).strip(),
        created_at=_moment(value.get("created_time")),
    )


def _moment(raw: Any) -> datetime | None:
    """Meta's unix timestamp as an aware datetime, or None.

    UTC and explicitly so. A naive datetime crossing into the Django layer
    is one Django warns about and then stores as if it were local time,
    which moves a lead by five hours in this deployment's timezone.
    """
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


__all__ = [
    "LEADGEN_FIELD",
    "SIGNATURE_PREFIX",
    "SUBSCRIBE_MODE",
    "LeadNotice",
    "leadgen_notices",
    "verification_challenge",
    "verify_signature",
]
