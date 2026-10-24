"""Graph API transport: the single source of truth for how we call Meta.

Every request in every project that uses this package goes through
:class:`GraphClient`, which is what gives timeouts, error translation and
the rate-limit check exactly one implementation.

There is no retry loop here. Retrying is a decision about the *caller*: a
Celery task can afford to wait a minute and try again, and an OAuth
callback with a person watching the browser cannot. So this raises
:class:`MetaTemporaryError` and lets the caller decide. The callers in
this product decide *against* automatic retries, every one of them with
its reason in its own docstring - a scheduled sync's next tick is the
retry, and a write that spends money must not run twice on a timeout.
"""

import json
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Final, Self

import httpx

from metaads import tracing
from metaads.errors import (
    AUTH_CODES,
    RATE_LIMIT_CODES,
    TRANSIENT_CODES,
    MetaAPIError,
    MetaAuthError,
    MetaPayloadTooLarge,
    MetaTemporaryError,
    PagesExhausted,
    RateLimitApproaching,
    describe,
    user_words,
)

# The one place the API version is written. Bumping Meta versions is a
# one-line change plus a changelog read, never a grep across the codebase.
API_VERSION: Final = "v26.0"
GRAPH_BASE_URL: Final = f"https://graph.facebook.com/{API_VERSION}"

# Where a person is sent to approve access. A different host from the API,
# and not a call we make - it is a URL we hand to a browser.
OAUTH_DIALOG_URL: Final = f"https://www.facebook.com/{API_VERSION}/dialog/oauth"

# Both halves are mandatory. A missing read timeout is how a worker ends up
# holding a connection until the queue backs up.
CONNECT_TIMEOUT_SECONDS: Final = 5.0
READ_TIMEOUT_SECONDS: Final = 30.0

# Uploads get their own, because they are the only calls whose duration
# depends on the size of the file rather than on Meta. Treat it as a ceiling
# on the whole transfer rather than per chunk: two hundred megabytes inside
# it needs about nine megabits a second.
UPLOAD_TIMEOUT_SECONDS: Final = 180.0

# Meta reports usage as a percentage on every response, and it reports it
# against **two separate budgets** that run out for different reasons.
#
# The business one is per ad account and per use case: one customer's
# heavy night cannot exhaust another's. The app one is a single figure
# shared by every customer of this deployment, so it is the one that
# starts to bind as the number of subscriptions grows - and unread, the
# first sign of it would be Meta blocking every account at once.
USAGE_HEADER: Final = "X-Business-Use-Case-Usage"
APP_USAGE_HEADER: Final = "X-App-Usage"
USAGE_STOP_PERCENT: Final = 80

# Paging ceiling, with one job: it bounds a cursor that points at itself.
# Hitting the ceiling raises :class:`PagesExhausted`, so a truncated
# answer cannot be mistaken for a complete one - a short list handed back
# silently is indistinguishable from a full one.
#
# It stays low as a *default* because most edges here are small - accounts,
# pages, forms - and a runaway cursor on one of those should stop early.
# The reads that legitimately page deep pass their own ceiling; see
# ``metaads.insights.MAX_INSIGHT_PAGES``.
MAX_PAGES: Final = 25

# The language every answer is asked for, and it is a decision rather than
# a preference. Meta localises to the ad account: the interest catalogue
# comes back as "Образование" on one account and "Education" on another
# with the same id, so a list searched by English name half fails - and
# the error messages localise with it, which puts the one sentence that
# explains a refusal in a language the person reading the log may not have.
#
# Pinned in one place because both problems have one answer.
API_LOCALE: Final = "en_US"

# The writes where that pin would be read as something else. Graph takes a
# query parameter and a body field as one list, and a lead form has a
# ``locale`` field of its own: the language of the buttons and the consent
# text the person filling it in reads. Pinned, every form would be created
# in English. Left out, Meta draws the form in the reader's own language -
# see ``metaads.specs.LeadFormSpec.locale``.
OWN_LOCALE_EDGES: Final = frozenset({"leadgen_forms"})


def _creates_own_locale(method: str, path: str) -> bool:
    """Whether this request creates an object whose ``locale`` is a field."""
    edge = path.rstrip("/").rsplit("/", 1)[-1]
    return method == "POST" and edge in OWN_LOCALE_EDGES


class GraphClient:
    """One conversation with the Graph API.

    Holds a token because every call in a conversation uses the same one,
    and holds an ``httpx.Client`` because connection reuse is most of the
    latency on a burst of small calls. Both are the caller's to supply and
    the caller's to close - the package reads no configuration and no
    environment.
    """

    def __init__(
        self,
        *,
        token: str = "",
        base_url: str = GRAPH_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
                write=READ_TIMEOUT_SECONDS,
                pool=CONNECT_TIMEOUT_SECONDS,
            )
        )
        self._owns_client = client is None
        self._brake = _Brake()

    # --- Lifecycle -------------------------------------------------------
    def for_token(self, token: str) -> "GraphClient":
        """The same connection pool, speaking as somebody else.

        Exists because of one real trap. A call taking both a ``token`` and
        an optional ``client`` looks like it uses the token and did not -
        the client was built with its own, and that one won silently.
        Creating a lead form is where this bites: it needs the *page* token,
        the account token is also valid, and Meta's answer names a missing
        permission rather than the wrong credential.

        The clone borrows the pool and so must never be closed, which it
        cannot be: ``_owns_client`` is false for anything built this way.
        """
        if token == self._token:
            return self
        clone = GraphClient(token=token, base_url=self._base_url, client=self._client)
        # And the same brake: the app-wide budget is one figure whoever is
        # speaking, so a stop one of them saw holds for both.
        clone._brake = self._brake
        return clone

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Only closes what it opened. A borrowed client stays open."""
        if self._owns_client:
            self._client.close()

    # --- Requests --------------------------------------------------------
    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self._request("GET", path, params=self._with_token(params))

    def post(self, path: str, **data: Any) -> dict[str, Any]:
        return self._request("POST", path, data=self._with_token(data))

    def delete(self, path: str, **params: Any) -> dict[str, Any]:
        """Remove one object. The rollback's only verb.

        A real DELETE rather than Meta's ``?method=delete`` shim, which also
        works: a POST in an access log where a delete happened is how an
        incident review loses an hour.
        """
        return self._request("DELETE", path, params=self._with_token(params))

    def delete_body(self, path: str, **data: Any) -> dict[str, Any]:
        """A DELETE whose subject is a body rather than a path.

        One edge needs it: removing people from a custom audience. What is
        being deleted is not the object the path names - the audience stays
        - it is a list of rows, and the list can run to ten thousand
        digests of sixty-four characters each. Put in the query string,
        that is most of a megabyte of URL, which proxies and access logs
        truncate long before Meta reads it.

        Meta's own documentation for that edge uses exactly this shape, and
        the token stays in the query where :meth:`delete` puts it, so a
        request appears in a trace looking like every other delete here.
        """
        return self._request("DELETE", path, params=self._with_token({}), data=data)

    def upload(
        self, path: str, *, files: dict[str, Any], **data: Any
    ) -> dict[str, Any]:
        """A multipart POST, for the one thing Meta will not take as a field.

        Its own timeout, and a long one: a phone video on a slow connection
        does not finish inside the read timeout every other call uses, and
        a write that dies mid-body uploads the whole file again.
        """
        return self._request(
            "POST",
            path,
            data=self._with_token(data),
            files=files,
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )

    def get_all(
        self, path: str, *, max_pages: int = MAX_PAGES, **params: Any
    ) -> list[dict[str, Any]]:
        """Follow cursor paging and return every row, or refuse to guess.

        Meta's default page is small and its cursors are absolute URLs, so
        the next request goes to the URL it gave us rather than to a path
        we build.

        **Reaching the ceiling raises rather than returning what it has.**
        That is the whole point of the ceiling. A short list and a
        complete one are the same object, so a caller cannot tell them
        apart - and the caller here is a nightly sync writing figures
        somebody prices their advertising against. Yesterday's correct
        total beside a staleness banner is worth more than today's total
        missing an unknown fraction.

        ``max_pages`` is per call because the edges differ by orders of
        magnitude: an account list is one page and a segment read on a busy
        account is dozens. A single number for both is either a ceiling
        that truncates real data or one that lets a broken cursor run.
        """
        rows: list[dict[str, Any]] = []
        payload = self.get(path, **params)

        for page in range(1, max_pages + 1):
            rows.extend(payload.get("data", []))
            following = payload.get("paging", {}).get("next")
            if not following:
                return rows
            if page == max_pages:
                raise PagesExhausted(
                    f"{path} still had pages after {max_pages}",
                    rows=rows,
                    pages=page,
                )
            payload = self._request("GET", following)

        return rows

    def _with_token(self, values: dict[str, Any]) -> dict[str, Any]:
        """Token in the query, which is what Meta's own examples use.

        An Authorization header also works, but every Meta error message,
        debugging tool and doc page assumes the parameter - and matching
        them is worth more than the small tidiness of a header.
        """
        return {**values, "access_token": self._token} if self._token else values

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        following = path_or_url.startswith("http")
        url = (
            path_or_url if following else f"{self._base_url}/{path_or_url.lstrip('/')}"
        )

        # Only on a URL we built. A paging cursor is absolute and already
        # carries every parameter the first request sent, this locale
        # included - and httpx *replaces* a query string rather than
        # merging into it, so adding one here would strip the cursor and
        # the access token along with it. Not on a write whose object has a
        # ``locale`` of its own either - see ``OWN_LOCALE_EDGES``.
        pinned = not following and not _creates_own_locale(method, path_or_url)
        query = {**(params or {}), "locale": API_LOCALE} if pinned else params

        # ``timeout`` is passed only when overridden: httpx reads an
        # explicit None as "wait forever", not as "use the client's".
        extra: dict[str, Any] = {"timeout": timeout} if timeout is not None else {}

        # The stop the last answer asked for, applied here rather than to
        # that answer - see ``_brake_on``.
        self._brake.check()

        started = time.perf_counter()
        try:
            response = self._client.request(
                method, url, params=query, data=data, files=files, **extra
            )
        except httpx.TimeoutException as exc:
            self._watched(method, url, query, data, started, error=str(exc))
            raise MetaTemporaryError(f"Meta did not answer in time: {exc}") from exc
        except httpx.TransportError as exc:
            self._watched(method, url, query, data, started, error=str(exc))
            raise MetaTemporaryError(f"could not reach Meta: {exc}") from exc

        # Before the status check, so a refusal is traced as fully as a
        # success. The call that is worth watching is almost never the one
        # that worked.
        self._watched(method, url, query, data, started, response=response)

        self._brake_on(response)

        if response.status_code >= 400:
            raise self._translate(response)

        payload = self._decode(response)

        # A 200 is not a promise. Meta answers some refusals with the
        # ordinary success status and an ``error`` object in the body -
        # account-level holds do this - and reading only the status code
        # would let one of those travel all the way to ``id_of`` as
        # "accepted the write and returned no id": a refusal Meta named
        # itself, turned into a message telling the advertiser to rewrite
        # their ad.
        if isinstance(payload.get("error"), Mapping):
            raise self._translate(response)

        return payload

    @staticmethod
    def _watched(
        method: str,
        url: str,
        query: dict[str, Any] | None,
        body: dict[str, Any] | None,
        started: float,
        *,
        response: httpx.Response | None = None,
        error: str = "",
    ) -> None:
        """Hand one attempt to whoever is watching. Costs nothing when
        nobody is - ``report`` returns on a missing watcher before touching
        anything, and it never raises."""
        if tracing.current() is None:
            return

        payload: Any = None
        if response is not None:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text[:2000]

        tracing.report(
            method=method,
            url=url,
            query=query,
            body=body,
            status=response.status_code if response is not None else 0,
            response=payload,
            ms=(time.perf_counter() - started) * 1000,
            error=error,
        )

    # --- Responses -------------------------------------------------------
    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaAPIError(
                f"Meta returned a non-JSON body ({response.status_code})"
            ) from exc

        # A bare `true` is what some writes answer with. Normalising here
        # means callers never have to check the type of what they got.
        if not isinstance(payload, dict):
            return {"result": payload}
        return payload

    @staticmethod
    def _translate(response: httpx.Response) -> MetaAPIError:
        """Turn one Meta error body into the right class to raise.

        The class is the decision, not the code: everything above this
        package branches on the type, so a new Meta code is a line in
        ``errors.py`` rather than a change in a service.
        """
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}

        code = error.get("code")
        subcode = error.get("error_subcode")
        title, sentence = user_words(error)
        # Every word Meta sent, not just ``message``. It is English,
        # technical, never shown to a user - and "Invalid parameter" on its
        # own is not enough to fix anything.
        message = describe(error, fallback=f"HTTP {response.status_code}")

        # Before the codes, because there are none: Meta answers an
        # oversized body with the status and nothing inside it.
        if response.status_code == httpx.codes.REQUEST_ENTITY_TOO_LARGE:
            return MetaPayloadTooLarge(message, code=code, subcode=subcode)
        if code in AUTH_CODES:
            return MetaAuthError(
                message,
                code=code,
                subcode=subcode,
                user_title=title,
                user_message=sentence,
            )
        # Transient before the limits, and by code. Meta also marks some
        # bodies ``is_transient``; that is honoured below, after the
        # limits, because a rate limit is never over in a minute whatever
        # the flag says. The subcode travels with both - it is what tells
        # one code 2 from another in a log.
        if code in TRANSIENT_CODES:
            return MetaTemporaryError(
                message,
                code=code,
                subcode=subcode,
                user_title=title,
                user_message=sentence,
            )
        if code in RATE_LIMIT_CODES:
            return RateLimitApproaching(
                message,
                code=code,
                subcode=subcode,
                user_title=title,
                user_message=sentence,
            )
        if error.get("is_transient") is True or response.status_code >= 500:
            return MetaTemporaryError(
                message,
                code=code,
                subcode=subcode,
                user_title=title,
                user_message=sentence,
            )
        return MetaAPIError(
            message,
            code=code,
            subcode=subcode,
            user_title=title,
            user_message=sentence,
        )

    def _brake_on(self, response: httpx.Response) -> None:
        """Set the brake when this answer says the budget is nearly gone.

        **The answer itself is kept.** Meta has already done the work and
        spent the budget on it; throwing a successful read away and raising
        instead spends the call for nothing, and on a paged read it loses
        every page before it. So the answer goes back to the caller and the
        stop lands on the next call this conversation makes.
        """
        try:
            self._check_usage(response)
        except RateLimitApproaching as stop:
            self._brake.stop = stop

    @staticmethod
    def _check_usage(response: httpx.Response) -> None:
        """Stop at 80 percent of a call budget rather than at 100.

        Past the real limit Meta blocks for minutes, which costs far more
        than the calls the last 20 percent would have bought.

        **Both budgets, and the worse of the two wins.** The business
        header is per account and per use case, so a heavy night on one
        customer stops that customer. The app header is one figure for
        this whole deployment: every subscription spends it, and unread,
        the first sign of it running out would be every account refused at
        once.

        A third budget exists - ``X-Ad-Account-Usage``, which counts the
        account's own write allowance - and is deliberately not read here.
        It governs a different thing (how many objects may be created)
        and refusing reads on it would stop syncing to protect writing.
        """
        worst = max(
            _worst_business_usage(response.headers.get(USAGE_HEADER)),
            _worst_app_usage(response.headers.get(APP_USAGE_HEADER)),
        )
        if worst >= USAGE_STOP_PERCENT:
            raise RateLimitApproaching(
                f"Meta usage at {worst:.0f} percent", percent=worst
            )


class _Brake:
    """A stop one answer asked for, held for the next call to meet.

    Its own object so a clone speaking with another token shares it - see
    :meth:`GraphClient.for_token`. Lives as long as the conversation: the
    callers build one client per read, so the next read starts clear and
    Meta's own headers decide again.
    """

    __slots__ = ("stop",)

    def __init__(self) -> None:
        self.stop: RateLimitApproaching | None = None

    def check(self) -> None:
        if self.stop is not None:
            raise RateLimitApproaching(str(self.stop), percent=self.stop.percent)


# The three figures Meta reports in either header. Percentages, all of
# them, and any one reaching the ceiling is enough - a call budget with
# CPU time left and no calls left is exhausted.
USAGE_FIGURES: Final = ("call_count", "total_cputime", "total_time")


def _worst_app_usage(raw: str | None) -> float:
    """The app-wide budget: one flat object, one deployment, every customer.

    ``{"call_count": 12, "total_cputime": 4, "total_time": 9}`` - no
    nesting, unlike its business-level neighbour, because there is nothing
    to key it by.
    """
    usage = _parsed(raw)
    if not isinstance(usage, dict):
        return 0.0
    return max((_number(usage.get(name)) for name in USAGE_FIGURES), default=0.0)


def _worst_business_usage(raw: str | None) -> float:
    """The per-account budget: an object keyed by id, holding lists.

    Shaped ``{"<account id>": [{...}, {...}]}``, so the worst figure
    across every account and every use case in the response is the one
    that matters - this call was made on behalf of one of them.
    """
    usage = _parsed(raw)
    if not isinstance(usage, dict):
        return 0.0
    return max(
        (
            _number(entry.get(name))
            for entries in usage.values()
            if isinstance(entries, list)
            for entry in entries
            if isinstance(entry, dict)
            for name in USAGE_FIGURES
        ),
        default=0.0,
    )


def _parsed(raw: str | None) -> Any:
    """The header as JSON, or ``None``. A malformed header is not our bug."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _number(value: Any) -> float:
    """One figure as a float. Meta has sent strings here before now."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
