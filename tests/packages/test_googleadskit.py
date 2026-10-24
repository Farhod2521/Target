"""googleadskit: the client, Google's refusals, and the account list."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from adskit.errors import (
    AccountActionRequired,
    AuthFailed,
    InvalidRequest,
    NotFound,
    PermissionDenied,
    RateLimited,
    TemporaryFailure,
)
from googleadskit import (
    API_VERSION,
    AdsClient,
    CustomerDTO,
    GoogleAdsAPIError,
    GoogleAdsOutcomeUnknown,
    GoogleAdsUnreachable,
    describe_customer,
    list_accounts,
    list_customer_ids,
    translate_error,
)
from googleadskit.errors import FailureReason

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler, **kwargs: Any) -> AdsClient:
    return AdsClient(
        token="tok", http=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs
    )


def _refusal(
    status_code: int, status: str, category: str = "", reason: str = "", **extra: Any
) -> httpx.Response:
    errors = [{"errorCode": {category: reason}, "message": "no", **extra}]
    body = {
        "error": {
            "code": status_code,
            "message": "Request had errors",
            "status": status,
            "details": [
                {
                    "@type": f"type.googleapis.com/google.ads.googleads.{API_VERSION}"
                    ".errors.GoogleAdsFailure",
                    "errors": errors if category else [],
                    "requestId": "req-1",
                }
            ],
        }
    }
    return httpx.Response(status_code, json=body)


def _customer_row(**fields: Any) -> dict[str, Any]:
    return {"results": [{"customer": fields}]}


# --- The client ---------------------------------------------------------


def test_the_token_goes_in_the_header_and_no_developer_token_is_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    with _client(handler) as client:
        client.get("customers:listAccessibleCustomers")

    request = seen[0]
    assert request.headers["Authorization"] == "Bearer tok"
    assert "developer-token" not in request.headers
    assert "login-customer-id" not in request.headers
    assert str(request.url).startswith(
        f"https://googleads.googleapis.com/{API_VERSION}/"
    )


def test_a_manager_id_is_sent_only_when_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    with _client(handler, login_customer_id="9876543210") as client:
        client.get("customers:listAccessibleCustomers")

    assert seen[0].headers["login-customer-id"] == "9876543210"


def test_search_follows_every_page() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "pageToken" not in body:
            return httpx.Response(
                200, json={"results": [{"n": 1}], "nextPageToken": "p2"}
            )
        return httpx.Response(200, json={"results": [{"n": 2}]})

    with _client(handler) as client:
        rows = list(client.search("123", "SELECT customer.id FROM customer"))

    assert rows == [{"n": 1}, {"n": 2}]
    assert bodies[1] == {"query": "SELECT customer.id FROM customer", "pageToken": "p2"}


def test_the_token_stays_out_of_the_repr() -> None:
    assert "tok" not in repr(_client(lambda _: httpx.Response(200)))


def test_a_refusal_keeps_everything_google_said() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return _refusal(
            429,
            "RESOURCE_EXHAUSTED",
            "quotaError",
            "RESOURCE_EXHAUSTED",
            details={"quotaErrorDetails": {"retryDelay": "30s"}},
        )

    with _client(handler) as client, pytest.raises(GoogleAdsAPIError) as caught:
        client.get("customers:listAccessibleCustomers")

    exc = caught.value
    assert exc.http_status == 429
    assert exc.status == "RESOURCE_EXHAUSTED"
    assert exc.reasons == (FailureReason("quotaError", "RESOURCE_EXHAUSTED"),)
    assert exc.request_id == "req-1"
    assert exc.retry_after_seconds == 30


def test_an_html_error_page_is_a_refusal_not_a_crash() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    with _client(handler) as client, pytest.raises(GoogleAdsAPIError) as caught:
        client.get("x")

    assert caught.value.http_status == 502


def test_a_request_that_never_left_is_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with _client(handler) as client, pytest.raises(GoogleAdsUnreachable):
        client.get("x")


def test_a_request_whose_answer_was_lost_is_an_unknown_outcome() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with _client(handler) as client, pytest.raises(GoogleAdsOutcomeUnknown):
        client.get("x")


# --- Translation --------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "category", "reason", "expected"),
    [
        pytest.param(
            "RESOURCE_EXHAUSTED",
            "quotaError",
            "RESOURCE_EXHAUSTED",
            RateLimited,
            id="quota",
        ),
        pytest.param(
            "UNAUTHENTICATED",
            "authenticationError",
            "OAUTH_TOKEN_REVOKED",
            AuthFailed,
            id="revoked",
        ),
        pytest.param(
            "PERMISSION_DENIED",
            "authorizationError",
            "USER_PERMISSION_DENIED",
            PermissionDenied,
            id="no-access",
        ),
        pytest.param(
            "PERMISSION_DENIED",
            "authorizationError",
            "CUSTOMER_NOT_ENABLED",
            AccountActionRequired,
            id="account-not-enabled",
        ),
        pytest.param(
            "PERMISSION_DENIED",
            "authorizationError",
            "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION",
            InvalidRequest,
            id="our-cloud-project",
        ),
        pytest.param("NOT_FOUND", "", "", NotFound, id="not-found"),
        pytest.param(
            "INTERNAL",
            "internalError",
            "TRANSIENT_ERROR",
            TemporaryFailure,
            id="transient",
        ),
        pytest.param(
            "INVALID_ARGUMENT",
            "queryError",
            "UNRECOGNIZED_FIELD",
            InvalidRequest,
            id="our-bug",
        ),
    ],
)
def test_google_refusals_become_the_domains_own(
    status: str, category: str, reason: str, expected: type
) -> None:
    reasons = (FailureReason(category, reason),) if category else ()
    exc = GoogleAdsAPIError("no", http_status=400, status=status, reasons=reasons)

    translated = translate_error(exc)

    assert type(translated) is expected
    assert translated.code == (reason or status)


def test_a_rate_limit_carries_googles_delay() -> None:
    exc = GoogleAdsAPIError(
        "slow down",
        http_status=429,
        status="RESOURCE_EXHAUSTED",
        retry_after_seconds=30,
    )

    translated = translate_error(exc)

    assert isinstance(translated, RateLimited)
    assert translated.retry_after_seconds == 30


def test_a_lost_answer_is_retryable_and_says_so() -> None:
    translated = translate_error(GoogleAdsOutcomeUnknown("lost"))

    assert isinstance(translated, TemporaryFailure)
    assert translated.code == "outcome_unknown"


# --- Accounts -----------------------------------------------------------


def test_customer_ids_come_out_of_resource_names() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"resourceNames": ["customers/1234567890", "customers/42"]}
        )

    with _client(handler) as client:
        assert list_customer_ids(client) == ["1234567890", "42"]


def test_a_customer_is_described_from_its_query_row() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/customers/1234567890/googleAds:search")
        return httpx.Response(
            200,
            json=_customer_row(
                id="1234567890",
                descriptiveName="Hunter",
                currencyCode="USD",
                timeZone="Asia/Tashkent",
                manager=False,
                testAccount=True,
                status="ENABLED",
            ),
        )

    with _client(handler) as client:
        customer = describe_customer(client, "1234567890")

    assert customer == CustomerDTO(
        id="1234567890",
        name="Hunter",
        currency="USD",
        time_zone="Asia/Tashkent",
        is_test=True,
        status="ENABLED",
    )
    assert customer.display_id == "123-456-7890"
    assert customer.can_advertise


def test_a_manager_account_cannot_advertise() -> None:
    assert not CustomerDTO(id="1", status="ENABLED", is_manager=True).can_advertise


def test_a_dead_account_is_left_out_of_the_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("listAccessibleCustomers"):
            return httpx.Response(
                200, json={"resourceNames": ["customers/111", "customers/222"]}
            )
        if "/customers/111/" in path:
            return _refusal(
                403, "PERMISSION_DENIED", "authorizationError", "CUSTOMER_NOT_ENABLED"
            )
        return httpx.Response(200, json=_customer_row(id="222", status="ENABLED"))

    with _client(handler) as client:
        accounts = list_accounts(client)

    assert [account.id for account in accounts] == ["222"]


def test_a_refusal_about_the_grant_still_fails_the_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("listAccessibleCustomers"):
            return httpx.Response(200, json={"resourceNames": ["customers/111"]})
        return _refusal(
            401, "UNAUTHENTICATED", "authenticationError", "OAUTH_TOKEN_REVOKED"
        )

    with _client(handler) as client, pytest.raises(GoogleAdsAPIError):
        list_accounts(client)
