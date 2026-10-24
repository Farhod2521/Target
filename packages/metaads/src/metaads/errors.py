"""Graph API failures, split by what the caller should do about them.

The split matters for Celery: ``MetaTemporaryError`` is what ``autoretry_for``
retries, and everything else must not be retried, because the same request
would fail the same way and only deepen the problem.
"""

import json
import re
from collections.abc import Mapping
from typing import Any

# Meta error codes worth retrying, in two sets because they call for
# opposite waits. A transient platform error is usually gone in a minute,
# and the request that met it may even have landed. A rate limit is the
# provider saying "not for a while", and asking again soon spends a
# budget that is already gone. One set for both would report a code 2
# ("service temporarily unavailable") as the call budget running out, and
# a launch that met one would skip its check for an object made anyway -
# a check that only makes sense after a transient failure.
#
# Everything else is a code or permission bug that a retry cannot fix.
#   1, 2      transient platform errors
TRANSIENT_CODES = frozenset({1, 2})
#   4, 17     application and user level rate limits
#   32        page level rate limit
#   613       custom rate limit
#   80000-80014  business use case limits, one code per use case (ads
#             insights, pages, Instagram, custom audiences, ads management,
#             lead ads, Messenger, WhatsApp, catalogues ...)
#   368       temporarily blocked. Not a token problem - the same token
#             works again once the block lifts - so it waits like a limit
#             rather than asking anybody to reconnect.
BUSINESS_USE_CASE_CODES = frozenset(range(80000, 80015))
TEMPORARY_BLOCK_CODES = frozenset({368})
RATE_LIMIT_CODES = (
    frozenset({4, 17, 32, 613}) | BUSINESS_USE_CASE_CODES | TEMPORARY_BLOCK_CODES
)
# Both, for a caller that only asks "retry or not".
RETRYABLE_CODES = TRANSIENT_CODES | RATE_LIMIT_CODES

# 190 invalid token, 200/294 missing permission.
# 31 is the odd one: the token is fine and the payload is fine, but the
# account is held until its owner does something in Meta's own console.
# It belongs here because the caller cannot fix it by sending anything
# different - which is the only question this set answers.
AUTH_CODES = frozenset({31, 190, 200, 294})


class MetaError(Exception):
    """Base for anything that went wrong while talking to Meta."""


class MetaAPIError(MetaError):
    """Meta answered with an error body. Permanent unless stated otherwise.

    ``code`` and ``subcode`` are Meta's own numbers: they belong in logs and
    never in a message shown to the user.
    """

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        subcode: int | None = None,
        user_title: str = "",
        user_message: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        # Meta's own two sentences for the advertiser. Carried separately
        # as well as folded into ``describe`` - the log line wants one
        # string, and a screen wants the half that was written for the
        # person reading it.
        self.user_title = user_title
        self.user_message = user_message


class MetaTemporaryError(MetaAPIError):
    """Transient: 5xx, timeout, a code in ``TRANSIENT_CODES``, or a body
    Meta marked ``is_transient`` that is not a rate limit."""


class MetaPayloadTooLarge(MetaAPIError):
    """HTTP 413: the request body was bigger than Meta takes in one request.

    It arrives with an empty body, so there is no code, no subcode and no
    sentence for the advertiser - the status is the whole of what is known.
    Without its own class that is an ``Invalid parameter``-shaped error
    with nothing inside it, and a screen reads it as a refused ad.
    """


class RateLimitApproaching(MetaTemporaryError):
    """Usage crossed the stop threshold, or Meta reported a rate limit.

    Raised at 80 percent, not at 100: past the real limit the ad account is
    blocked and recovery takes minutes, so the last 20 percent buys nothing.

    ``retry_after`` is in seconds, derived from Meta's
    ``estimated_time_to_regain_access``.
    """

    def __init__(
        self,
        message: str = "Meta rate limit threshold reached",
        *,
        percent: float | None = None,
        retry_after: int | None = None,
        code: int | None = None,
        subcode: int | None = None,
        user_title: str = "",
        user_message: str = "",
    ) -> None:
        super().__init__(
            message,
            code=code,
            subcode=subcode,
            user_title=user_title,
            user_message=user_message,
        )
        self.percent = percent
        self.retry_after = retry_after


class MetaAuthError(MetaAPIError):
    """Token expired, revoked, or missing a permission. Needs a human."""


class PagesExhausted(MetaError):
    """A cursor loop hit its ceiling while Meta still had pages to give.

    **Not an error Meta reported.** Every request succeeded; there were
    simply more rows than the loop was allowed to fetch. It is raised
    rather than returned because a short list handed back at the ceiling
    is indistinguishable from a complete one: a ninety-day breakdown that
    loses a third of its rows produces a dashboard that is quietly wrong,
    with nothing anywhere to say so.

    Two readings, and the ceiling cannot tell them apart:

    * a cursor pointing at itself, which is a provider bug and would spin
      until something killed the worker;
    * a genuinely large answer, which is what a busy account's segment
      read is.

    Both have the same right answer here - stop, and say so. The caller
    decides whether to keep what it already stored, ask for a narrower
    window, or give up for the night.

    ``rows`` carries what was read, for a caller that has a use for a
    partial answer. Nothing in this product does: a spend figure short by
    an unknown amount is worse than yesterday's, which is why the metrics
    sync lets this become a failed step and keeps the figures it had.
    """

    def __init__(
        self,
        message: str,
        *,
        rows: list[Any] | None = None,
        pages: int = 0,
    ) -> None:
        super().__init__(message)
        self.rows = rows or []
        self.pages = pages


def describe(error: Mapping[str, Any], *, fallback: str) -> str:
    """Everything Meta said about one failure, as a single line for the log.

    ``message`` is often the least useful field in the body: "Invalid
    parameter" names no parameter, and on a six-call creation sequence that
    is indistinguishable from "something, somewhere". The fields beside it -
    ``error_user_title``, ``error_user_msg`` and the blamed field specs -
    are the ones that say which value was refused, and dropping them turns a
    one-line fix into a guessing game against somebody else's API.

    Never shown to a customer. This is English, technical, and belongs in a
    log line and an audit row - which is exactly where it is kept.

    The numbers go in it too, and they earn their place: Meta localises
    these sentences to the account, so the same refusal has been seen in
    Russian, Uzbek and English. A code and a subcode are the only part of
    an error that reads the same in all three, and they are what a check
    for "is this that failure again" has to match on.
    """
    parts = [str(error.get("message") or "").strip() or fallback]

    for key in ("error_user_title", "error_user_msg"):
        value = str(error.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)

    blamed = _blamed(error)
    if blamed:
        parts.append(f"blamed: {blamed}")

    numbers = _numbers(error)
    if numbers:
        parts.append(numbers)

    return " | ".join(parts)


# The array Meta appends to ``error_user_msg`` when it refuses an audience
# for naming a catalogue entry it has withdrawn. Four fields, JSON, inside
# an otherwise ordinary English sentence:
#
#   ... Relevant alternative options: [{"deprecated_interest_id":"600333...",
#   "deprecated_interest_name":"Tea house","alternative_interest_id":"6003...",
#   "alternative_interest_name":"Tea"}]
_RETIRED_ARRAY = re.compile(r"\[\s*\{.*}\s*]", re.DOTALL)


def retired_pairs(message: str) -> list[dict[str, str]]:
    """Every withdrawn option named in one refusal, with its replacement.

    **Matched on the payload rather than on a subcode**, which is the
    opposite of every other check in this package and is deliberate. The
    field names inside that array are Meta's own and are not localised, so
    reading them is not a match on a sentence - and the array is the only
    place the replacement exists. A subcode would say *that* something is
    retired; this says *what*, which is the half a screen can act on.

    The rule is honest about its own limit: this failure is claimed only
    when the mapping can be read out of the message.

    Never raises. A diagnostic that throws while explaining a failure hides
    the failure it was written to explain.
    """
    found = _RETIRED_ARRAY.search(message or "")
    if found is None:
        return []

    try:
        rows = json.loads(found.group(0))
    except ValueError:
        return []
    if not isinstance(rows, list):
        return []

    pairs: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        retired = str(row.get("deprecated_interest_id") or "").strip()
        if not retired:
            continue
        pairs.append(
            {
                "retired_id": retired,
                "retired_name": str(row.get("deprecated_interest_name") or "").strip(),
                # Empty is a real answer: Meta withdraws options with
                # nothing in their place, and the option simply goes.
                "alternative_id": str(row.get("alternative_interest_id") or "").strip(),
                "alternative_name": str(
                    row.get("alternative_interest_name") or ""
                ).strip(),
            }
        )
    return pairs


def _numbers(error: Mapping[str, Any]) -> str:
    """``code 100/1815227`` - the language-independent half of a refusal."""
    code = error.get("code")
    if code is None:
        return ""
    subcode = error.get("error_subcode")
    return f"code {code}" + (f"/{subcode}" if subcode else "")


def _blamed(error: Mapping[str, Any]) -> str:
    """The field names Meta refused, when it named any.

    ``error_data`` arrives as an object on most edges and as a JSON string
    on a few - Meta's inconsistency, not ours - so both shapes are read and
    neither is allowed to raise. A diagnostic that can itself throw while
    explaining a failure hides the failure it was written to explain.
    """
    data: Any = error.get("error_data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return ""

    if not isinstance(data, Mapping):
        return ""

    specs = data.get("blame_field_specs")
    if not isinstance(specs, list):
        return ""

    # Meta nests these one level deep - [["daily_budget"]] - but not always.
    names: list[str] = []
    for group in specs:
        entries = group if isinstance(group, list) else [group]
        names.extend(str(entry).strip() for entry in entries)

    return ", ".join(name for name in names if name)


def user_words(error: Mapping[str, Any]) -> tuple[str, str]:
    """The pair Meta wrote for the advertiser: a title and a sentence.

    Separate from :func:`describe`, which is for a log. These two are the
    only fields in an error body that Meta writes for the person who owns
    the ad account rather than for the developer calling the API - which
    is what makes them the only two a product screen may repeat.
    """
    return (
        str(error.get("error_user_title") or "").strip(),
        str(error.get("error_user_msg") or "").strip(),
    )
