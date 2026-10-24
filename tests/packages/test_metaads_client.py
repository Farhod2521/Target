"""The Graph transport.

No network: every response here is a recorded shape from Meta's own
documentation, served through an httpx mock transport. What is being
tested is the translation - one Meta error body into one class the rest of
the system knows how to treat.
"""

import json

import httpx
import pytest
from metaads.client import API_LOCALE, USAGE_HEADER, GraphClient
from metaads.errors import (
    MetaAPIError,
    MetaAuthError,
    MetaPayloadTooLarge,
    MetaTemporaryError,
    PagesExhausted,
    RateLimitApproaching,
)


def client_returning(
    *responses: httpx.Response, capture: list[httpx.Request] | None = None
) -> GraphClient:
    """A GraphClient wired to a scripted transport instead of the network."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return queue.pop(0) if queue else responses[-1]

    return GraphClient(
        token="test-token", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def error_body(code: int, message: str = "boom") -> httpx.Response:
    return httpx.Response(400, json={"error": {"message": message, "code": code}})


# --- Happy path ----------------------------------------------------------
def test_a_get_returns_the_decoded_body() -> None:
    graph = client_returning(httpx.Response(200, json={"id": "123"}))

    assert graph.get("me")["id"] == "123"


def test_the_token_travels_with_every_call() -> None:
    seen: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json={}), capture=seen)

    graph.get("me")

    assert "access_token=test-token" in str(seen[0].url)


def test_a_borrowed_connection_can_speak_as_somebody_else() -> None:
    """Creating a lead form needs the page's token while everything around
    it uses the account's. Both are valid, so sending the wrong one is not
    an error - it is a permission message about the right object."""
    seen: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json={}), capture=seen)

    graph.for_token("page-token").get("me")

    assert "access_token=page-token" in str(seen[0].url)


def test_the_same_token_borrows_nothing() -> None:
    graph = client_returning(httpx.Response(200, json={}))

    assert graph.for_token("test-token") is graph


def test_a_clone_does_not_close_the_pool_it_borrowed() -> None:
    """It shares the connection pool. Closing it would take the original's
    connections with it, mid-sequence."""
    graph = client_returning(httpx.Response(200, json={}))

    graph.for_token("other").close()

    assert graph.get("me") == {}


def test_a_bare_true_is_still_a_dict() -> None:
    """Some writes answer with `true`. Callers should not have to type-check."""
    graph = client_returning(httpx.Response(200, json=True))

    assert graph.post("act_1/ads")["result"] is True


def test_a_non_json_body_is_an_api_error_not_a_crash() -> None:
    graph = client_returning(httpx.Response(200, text="<html>maintenance</html>"))

    with pytest.raises(MetaAPIError):
        graph.get("me")


# --- Paging --------------------------------------------------------------
def test_paging_follows_the_cursor_meta_gave_us() -> None:
    first = httpx.Response(
        200,
        json={
            "data": [{"id": "1"}],
            "paging": {
                "next": "https://graph.facebook.com/v26.0/me/adaccounts?after=x"
            },
        },
    )
    second = httpx.Response(200, json={"data": [{"id": "2"}]})
    graph = client_returning(first, second)

    rows = graph.get_all("me/adaccounts")

    assert [row["id"] for row in rows] == ["1", "2"]


def test_a_cursor_pointing_at_itself_cannot_spin_forever() -> None:
    """MAX_PAGES is the difference between a bug and a killed worker."""
    looping = httpx.Response(
        200,
        json={
            "data": [{"id": "1"}],
            "paging": {"next": "https://graph.facebook.com/v26.0/me/adaccounts"},
        },
    )
    graph = client_returning(looping)

    with pytest.raises(PagesExhausted) as caught:
        graph.get_all("me/adaccounts")

    assert caught.value.pages == 25


def test_hitting_the_ceiling_refuses_rather_than_shortening_the_answer() -> None:
    """The failure a silent ceiling *is*.

    A read that stops at its ceiling and returns what it has produces a
    list indistinguishable from a complete one, and the caller stores it
    as fact. That is how a segment sync loses a third of its rows every
    night with nothing anywhere to say so.
    """
    deep = httpx.Response(
        200,
        json={
            "data": [{"id": "1"}],
            "paging": {"next": "https://graph.facebook.com/v26.0/act_1/insights?p=2"},
        },
    )
    graph = client_returning(deep)

    with pytest.raises(PagesExhausted) as caught:
        graph.get_all("act_1/insights", max_pages=3)

    # What it managed is carried rather than thrown away - a log line can
    # then say how close the window was to fitting.
    assert caught.value.pages == 3
    assert len(caught.value.rows) == 3


def test_a_read_that_finishes_inside_its_ceiling_is_untouched() -> None:
    """The ordinary case: the ceiling is a guard, not a limit."""
    last = httpx.Response(200, json={"data": [{"id": "2"}]})
    first = httpx.Response(
        200,
        json={
            "data": [{"id": "1"}],
            "paging": {"next": "https://graph.facebook.com/v26.0/me/adaccounts?p=2"},
        },
    )
    graph = client_returning(first, last)

    rows = graph.get_all("me/adaccounts", max_pages=200)

    assert [row["id"] for row in rows] == ["1", "2"]


# --- One language, on every call -----------------------------------------
def test_every_request_asks_meta_to_answer_in_english() -> None:
    """Two problems with one answer: the interest catalogue localises its
    names, and the error messages localise with them - which puts the one
    sentence explaining a refusal in a language the log's reader may not
    have."""
    seen: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json={"id": "1"}), capture=seen)

    graph.get("me")
    graph.post("act_1/campaigns", name="x")
    graph.delete("120210")

    assert all(f"locale={API_LOCALE}" in str(request.url) for request in seen)
    assert API_LOCALE == "en_US"


def test_a_post_carries_the_locale_in_the_query_and_not_in_the_body() -> None:
    """A field in the body is a field on the object being created. This one
    is a request parameter and has to stay one."""
    seen: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json={"id": "1"}), capture=seen)

    graph.post("act_1/campaigns", name="Osh markazi")

    assert "locale" in str(seen[0].url)
    assert "locale" not in seen[0].content.decode()


def test_a_lead_form_is_created_without_the_pin() -> None:
    """A lead form's ``locale`` is a field on the form, and Graph reads a
    query parameter as one. Pinned, a form would open in English for
    somebody who reads Uzbek or Russian. Reading the forms back keeps it."""
    seen: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json={"id": "1"}), capture=seen)

    graph.post("1305481949308392/leadgen_forms", name="Lidlar")
    graph.get("1305481949308392/leadgen_forms")

    assert "locale" not in str(seen[0].url)
    assert "locale" not in seen[0].content.decode()
    assert f"locale={API_LOCALE}" in str(seen[1].url)


def test_a_paging_cursor_keeps_every_parameter_meta_put_in_it() -> None:
    """httpx *replaces* a query string rather than merging into it, so
    adding a locale to a cursor would strip the cursor - and the access
    token with it - turning paging into the first page, twenty-five times."""
    seen: list[httpx.Request] = []
    first = httpx.Response(
        200,
        json={
            "data": [{"id": "1"}],
            "paging": {
                "next": (
                    "https://graph.facebook.com/v26.0/me/adaccounts"
                    "?after=CURSOR&access_token=T&locale=en_US"
                )
            },
        },
    )
    graph = client_returning(
        first, httpx.Response(200, json={"data": []}), capture=seen
    )

    graph.get_all("me/adaccounts")

    followed = str(seen[1].url)
    assert "after=CURSOR" in followed
    assert "access_token=T" in followed


# --- Error translation ---------------------------------------------------
@pytest.mark.parametrize(
    "code",
    [
        pytest.param(190, id="expired-token"),
        pytest.param(200, id="missing-permission"),
        pytest.param(294, id="missing-permission-2"),
        pytest.param(31, id="account-held-pending-action"),
    ],
)
def test_an_auth_code_needs_a_human(code: int) -> None:
    """Not retryable: the same token fails the same way every time."""
    graph = client_returning(error_body(code))

    with pytest.raises(MetaAuthError):
        graph.get("me")


@pytest.mark.parametrize(
    "code",
    [
        pytest.param(4, id="app-rate-limit"),
        pytest.param(17, id="user-rate-limit"),
        pytest.param(32, id="page-rate-limit"),
        pytest.param(613, id="custom-rate-limit"),
        pytest.param(368, id="temporarily-blocked"),
        *(
            pytest.param(code, id=f"business-use-case-{code}")
            for code in range(80000, 80015)
        ),
    ],
)
def test_a_rate_limit_code_is_retryable(code: int) -> None:
    graph = client_returning(error_body(code))

    with pytest.raises(RateLimitApproaching) as caught:
        graph.get("me")

    assert isinstance(caught.value, MetaTemporaryError)
    assert caught.value.code == code


@pytest.mark.parametrize("code", [32, 368, 80000, 80014])
def test_a_limit_is_never_read_as_a_bad_token(code: int) -> None:
    """A temporary block lifts by itself with the same token. Read as an
    auth failure it marked the connection unusable and asked the owner to
    reconnect - which fixes nothing."""
    graph = client_returning(error_body(code))

    with pytest.raises(MetaAPIError) as caught:
        graph.get("me")

    assert not isinstance(caught.value, MetaAuthError)


def test_the_codes_just_past_the_business_range_are_not_limits() -> None:
    graph = client_returning(error_body(80015))

    with pytest.raises(MetaAPIError) as caught:
        graph.get("me")

    assert not isinstance(caught.value, RateLimitApproaching)


def test_a_server_error_is_retryable() -> None:
    graph = client_returning(httpx.Response(503, json={"error": {"message": "nope"}}))

    with pytest.raises(MetaTemporaryError):
        graph.get("me")


def test_our_own_bad_payload_is_not_retryable() -> None:
    """Code 100 is "you sent nonsense". Retrying sends the same nonsense."""
    graph = client_returning(error_body(100, "Invalid parameter"))

    with pytest.raises(MetaAPIError) as caught:
        graph.get("me")

    assert not isinstance(caught.value, MetaTemporaryError)


def test_metas_own_wording_is_kept_for_the_log() -> None:
    """Kept to be logged, never to be shown - it is English and technical."""
    graph = client_returning(error_body(100, "Invalid parameter: adset_id"))

    with pytest.raises(MetaAPIError, match="adset_id"):
        graph.get("me")


def test_the_explanation_beside_the_message_is_kept_too() -> None:
    """ "Invalid parameter" names no parameter. Everything that does is in
    the fields next to it, and dropping them is how a one-line fix becomes
    a guessing game."""
    graph = client_returning(
        httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid parameter",
                    "code": 100,
                    "error_user_title": "Ad Account Not Set Up",
                    "error_user_msg": "Add a payment method to this account.",
                }
            },
        )
    )

    with pytest.raises(MetaAPIError) as caught:
        graph.get("me")

    said = str(caught.value)
    assert "Invalid parameter" in said
    assert "Ad Account Not Set Up" in said
    assert "payment method" in said


def test_the_refused_field_is_named_when_meta_names_it() -> None:
    graph = client_returning(
        httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid parameter",
                    "code": 100,
                    "error_data": {"blame_field_specs": [["daily_budget"]]},
                }
            },
        )
    )

    with pytest.raises(MetaAPIError, match="daily_budget"):
        graph.get("me")


def test_a_blame_block_sent_as_a_string_is_read_too() -> None:
    """Meta sends ``error_data`` as an object on most edges and as a JSON
    string on a few. A diagnostic that throws while explaining a failure
    hides the failure it exists to explain."""
    graph = client_returning(
        httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid parameter",
                    "code": 100,
                    "error_data": json.dumps(
                        {"blame_field_specs": [["promoted_object"]]}
                    ),
                }
            },
        )
    )

    with pytest.raises(MetaAPIError, match="promoted_object"):
        graph.get("me")


def test_a_blame_block_that_makes_no_sense_is_survived() -> None:
    graph = client_returning(
        httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid parameter",
                    "code": 100,
                    "error_data": "not json at all",
                }
            },
        )
    )

    with pytest.raises(MetaAPIError, match="Invalid parameter"):
        graph.get("me")


def test_a_timeout_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(MetaTemporaryError):
        graph.get("me")


def test_an_unreachable_host_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(MetaTemporaryError):
        graph.get("me")


# --- Rate limit header ---------------------------------------------------
def usage_header(percent: int) -> dict[str, str]:
    return {
        USAGE_HEADER: json.dumps(
            {"act_1": [{"type": "ads_management", "call_count": percent}]}
        )
    }


def test_the_next_call_stops_at_eighty_percent() -> None:
    """Past the real limit Meta blocks the account for minutes."""
    graph = client_returning(
        httpx.Response(200, json={"id": "1"}, headers=usage_header(80))
    )
    graph.get("me")

    with pytest.raises(RateLimitApproaching):
        graph.get("me")


def test_the_answer_that_crossed_the_line_is_kept() -> None:
    """Meta already did the work and spent the budget on it. Throwing a
    successful read away spends the call for nothing."""
    graph = client_returning(
        httpx.Response(200, json={"id": "1"}, headers=usage_header(95))
    )

    assert graph.get("me")["id"] == "1"


def test_the_stopped_call_is_never_sent() -> None:
    sent: list[httpx.Request] = []
    graph = client_returning(
        httpx.Response(200, json={"id": "1"}, headers=usage_header(90)),
        capture=sent,
    )
    graph.get("me")

    with pytest.raises(RateLimitApproaching):
        graph.get("me")

    assert len(sent) == 1


def test_a_paged_read_stops_at_the_page_after_the_line() -> None:
    """The page that crossed is kept by the transport; the next one is not
    asked for, and a short list is never handed back as a whole one."""
    sent: list[httpx.Request] = []
    graph = client_returning(
        httpx.Response(
            200,
            json={"data": [{"id": "1"}], "paging": {"next": "https://graph/next"}},
            headers=usage_header(85),
        ),
        capture=sent,
    )

    with pytest.raises(RateLimitApproaching):
        graph.get_all("act_1/campaigns")

    assert len(sent) == 1


def test_a_clone_speaking_as_somebody_else_meets_the_same_stop() -> None:
    graph = client_returning(
        httpx.Response(200, json={"id": "1"}, headers=usage_header(90))
    )
    graph.get("me")

    with pytest.raises(RateLimitApproaching):
        graph.for_token("page-token").get("me")


def test_below_the_threshold_the_call_goes_through() -> None:
    graph = client_returning(
        httpx.Response(200, json={"id": "1"}, headers=usage_header(79))
    )

    assert graph.get("me")["id"] == "1"


def test_the_worst_number_in_the_header_wins() -> None:
    """The header carries three measures; any one of them can be the problem."""
    header = {
        USAGE_HEADER: json.dumps(
            {"act_1": [{"call_count": 10, "total_cputime": 95, "total_time": 20}]}
        )
    }
    graph = client_returning(httpx.Response(200, json={}, headers=header))
    graph.get("me")

    with pytest.raises(RateLimitApproaching, match="95"):
        graph.get("me")


def test_a_malformed_usage_header_is_ignored() -> None:
    """A header we cannot parse must not take down a working call."""
    graph = client_returning(
        httpx.Response(200, json={"id": "1"}, headers={USAGE_HEADER: "not json"})
    )

    assert graph.get("me")["id"] == "1"


# --- Lifecycle -----------------------------------------------------------
def test_a_borrowed_client_is_not_closed() -> None:
    """Closing somebody else's pool shows up as an unrelated timeout later."""
    borrowed = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    graph = GraphClient(token="t", client=borrowed)

    graph.close()

    assert not borrowed.is_closed


# --- When 200 does not mean yes ------------------------------------------
# Meta answers some refusals with the ordinary success status and an
# ``error`` object in the body. An account held pending a security check
# does this, and reading only the status code lets that refusal travel past
# every error path in the package and surface four calls later as "the
# write was accepted and returned no id" - which sends an advertiser back to
# rewrite an ad three times over a confirmation button in Ads Manager.
HELD = {
    "error": {
        "message": "This request requires the user to take a pending action",
        "type": "OAuthException",
        "code": 31,
        "error_subcode": 3858385,
        "error_user_title": "Please authenticate your account",
    }
}


def test_an_oversized_upload_is_named_by_its_status() -> None:
    """Meta answers 413 with an empty body: no code, no sentence. The
    status is all there is, and without it the refusal reads as a bad ad."""
    graph = client_returning(httpx.Response(413, content=b""))

    with pytest.raises(MetaPayloadTooLarge) as caught:
        graph.post("act_1/advideos", name="x")

    assert "HTTP 413" in str(caught.value)


def test_an_error_body_is_an_error_whatever_the_status_says() -> None:
    graph = client_returning(httpx.Response(200, json=HELD))

    with pytest.raises(MetaAuthError) as caught:
        graph.post("act_1/ads", name="x")

    assert caught.value.code == 31
    assert caught.value.subcode == 3858385


def test_the_held_account_explains_itself_in_the_message() -> None:
    """The title is the half a person can act on."""
    graph = client_returning(httpx.Response(200, json=HELD))

    with pytest.raises(MetaAuthError) as caught:
        graph.post("act_1/ads", name="x")

    assert "authenticate your account" in str(caught.value)
    assert "code 31/3858385" in str(caught.value)


def test_a_body_with_no_error_is_left_alone() -> None:
    """The check must not turn an ordinary answer into a failure."""
    graph = client_returning(
        httpx.Response(200, json={"id": "9", "name": "error-free"})
    )

    assert graph.get("9") == {"id": "9", "name": "error-free"}


def test_an_error_shaped_value_that_is_not_an_error_object_passes() -> None:
    """Only Meta's own shape counts - an object under the key. A field that
    happens to be called error and holds a string is somebody's data."""
    graph = client_returning(httpx.Response(200, json={"id": "9", "error": ""}))

    assert graph.get("9")["id"] == "9"


# --- The two sentences Meta writes for the advertiser --------------------
# `message` is written for whoever called the API and is routinely useless
# to the person who owns the account: "Invalid parameter" names no
# parameter. The pair beside it is the opposite - written for the
# advertiser, and often the only part that says what to do. It has to
# survive translation into a domain error, because a screen that cannot
# reach it can only say "the provider said no".
def test_metas_own_words_for_the_advertiser_are_carried_separately() -> None:
    graph = client_returning(
        httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid parameter",
                    "code": 100,
                    "error_subcode": 1815316,
                    "error_user_title": "Lead Ad Creative Does Not Use External URL",
                    "error_user_msg": "Fix this by changing the URL.",
                }
            },
        )
    )

    with pytest.raises(MetaAPIError) as caught:
        graph.post("act_1/adcreatives", name="x")

    assert caught.value.user_title.startswith("Lead Ad Creative")
    assert caught.value.user_message == "Fix this by changing the URL."


def test_a_refusal_with_no_advertiser_words_carries_none() -> None:
    """Most of them. A screen that promises an explanation it does not
    have is worse than one that stays with its own sentence."""
    graph = client_returning(error_body(100))

    with pytest.raises(MetaAPIError) as caught:
        graph.get("me")

    assert caught.value.user_title == ""
    assert caught.value.user_message == ""


def test_the_log_line_still_carries_everything() -> None:
    """Splitting the pair out must not thin the string support reads."""
    graph = client_returning(
        httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid parameter",
                    "code": 100,
                    "error_subcode": 1815316,
                    "error_user_title": "Lead Ad Creative",
                }
            },
        )
    )

    with pytest.raises(MetaAPIError) as caught:
        graph.get("me")

    assert "Invalid parameter" in str(caught.value)
    assert "Lead Ad Creative" in str(caught.value)
    assert "code 100/1815316" in str(caught.value)
