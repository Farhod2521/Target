"""Which class each Meta failure arrives as - the decision every caller reads.

One table, because the table is the contract. A code in the wrong row fails
loudly nowhere: a transient hiccup reported as the call budget running out
reads as a rate limit in every log, skips the launch's check for an object
made anyway, and tells somebody to wait out a limit nobody hit.
"""

from typing import Any

import httpx
import pytest
from adskit.errors import (
    AccountActionRequired,
    AuthFailed,
    InvalidRequest,
    RateLimited,
    TemporaryFailure,
)
from metaads.adapter import translate_error
from metaads.client import GraphClient
from metaads.errors import (
    MetaAPIError,
    MetaAuthError,
    MetaTemporaryError,
    RateLimitApproaching,
)


def refusal(status: int, **error: Any) -> httpx.Response:
    """One error body, as Meta sends it."""
    return httpx.Response(status, json={"error": {"message": "refused", **error}})


@pytest.mark.parametrize(
    ("status", "error", "meta_class", "domain_class"),
    [
        pytest.param(400, {"code": 1}, MetaTemporaryError, TemporaryFailure, id="1"),
        pytest.param(400, {"code": 2}, MetaTemporaryError, TemporaryFailure, id="2"),
        pytest.param(
            400,
            {"code": 2, "error_subcode": 1504044},
            MetaTemporaryError,
            TemporaryFailure,
            id="2/1504044",
        ),
        pytest.param(400, {"code": 4}, RateLimitApproaching, RateLimited, id="4"),
        pytest.param(400, {"code": 17}, RateLimitApproaching, RateLimited, id="17"),
        pytest.param(400, {"code": 613}, RateLimitApproaching, RateLimited, id="613"),
        pytest.param(
            400, {"code": 80004}, RateLimitApproaching, RateLimited, id="80004"
        ),
        # A limit stays a limit, whatever the flag says.
        pytest.param(
            400,
            {"code": 17, "is_transient": True},
            RateLimitApproaching,
            RateLimited,
            id="17-marked-transient",
        ),
        pytest.param(400, {"code": 190}, MetaAuthError, AuthFailed, id="190"),
        pytest.param(503, {}, MetaTemporaryError, TemporaryFailure, id="5xx"),
        pytest.param(
            400,
            {"code": 999, "is_transient": True},
            MetaTemporaryError,
            TemporaryFailure,
            id="unknown-marked-transient",
        ),
        pytest.param(400, {"code": 999}, MetaAPIError, InvalidRequest, id="unknown"),
        # Meta's identity hold, as it arrived in production: HTTP 200 and an
        # error in the body, flagged not transient. A hold that read as a
        # hiccup would be retried into the same refusal.
        pytest.param(
            200,
            {"code": 31, "error_subcode": 3858385, "is_transient": False},
            MetaAuthError,
            AccountActionRequired,
            id="31/3858385",
        ),
    ],
)
def test_each_failure_arrives_as_the_class_that_says_what_to_do(
    status: int, error: dict[str, Any], meta_class: type, domain_class: type
) -> None:
    raised = GraphClient._translate(refusal(status, **error))

    assert type(raised) is meta_class
    assert type(translate_error(raised)) is domain_class


@pytest.mark.parametrize("code", [2, 17])
def test_the_subcode_travels_with_a_transient_failure_and_a_limit(code: int) -> None:
    """It is what tells one code 2 from another in a log."""
    raised = GraphClient._translate(refusal(400, code=code, error_subcode=1504044))

    assert isinstance(raised, MetaAPIError)
    assert raised.subcode == 1504044
    assert "code " + str(code) + "/1504044" in str(raised)
