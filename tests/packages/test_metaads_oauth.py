"""The connect handshake, and what a token reaches once it exists."""

import httpx
import pytest
from metaads.accounts import list_ad_accounts, list_pages, may_advertise
from metaads.client import GraphClient
from metaads.errors import MetaAPIError
from metaads.oauth import (
    DEFAULT_SCOPES,
    OPTIONAL_SCOPES,
    REQUIRED_SCOPES,
    authorize_url,
    describe_person,
    exchange_code,
    exchange_for_long_lived,
    holds,
    inspect_token,
    missing,
    revoke_access,
)

from tests.packages.test_metaads_client import client_returning, error_body


# --- The dialog URL ------------------------------------------------------
def test_the_dialog_url_carries_what_meta_needs() -> None:
    url = authorize_url(
        app_id="123", redirect_uri="https://example.com/cb/", state="abc"
    )

    assert url.startswith("https://www.facebook.com/v26.0/dialog/oauth?")
    assert "client_id=123" in url
    assert "state=abc" in url
    assert "response_type=code" in url


def test_the_redirect_uri_is_encoded() -> None:
    """Meta compares this string exactly; a raw slash breaks the match."""
    url = authorize_url(
        app_id="123", redirect_uri="https://example.com/cb/", state="abc"
    )

    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcb%2F" in url


def test_every_permission_is_asked_for_once() -> None:
    """Asking again in May reads as March not having worked.

    The count is pinned on purpose: a scope added here widens what every
    consent screen asks for and, worse, does nothing at all for tokens
    already issued - so it has to be a decision somebody made, not a line
    that arrived with something else.
    """
    url = authorize_url(app_id="1", redirect_uri="https://e.com/", state="s")

    for scope in ("ads_management", "leads_retrieval", "pages_manage_metadata"):
        assert scope in url
    assert len(DEFAULT_SCOPES) == 9


def test_the_dialog_asks_for_the_optional_half_too() -> None:
    """One prompt, not two. The permission is optional to a *launch* and
    not to the consent screen: asking for it later would be a second trip
    through Meta's dialog for somebody who already granted everything."""
    url = authorize_url(app_id="1", redirect_uri="https://e.com/", state="s")

    assert "instagram_basic" in url


def test_the_permission_a_lead_form_needs_is_asked_for() -> None:
    """Its absence is invisible until the fifth call of a creation
    sequence: Meta answers POST /{page_id}/leadgen_forms with "#200
    requires pages_manage_ads", which names the permission but not the
    fact that it was never asked for. A page token inherits the user
    token's grants, so the form could never be created."""
    url = authorize_url(app_id="1", redirect_uri="https://e.com/", state="s")

    assert "pages_manage_ads" in url


# --- Exchanges -----------------------------------------------------------
def test_a_code_becomes_a_token() -> None:
    graph = client_returning(
        httpx.Response(200, json={"access_token": "short", "expires_in": 3600})
    )

    token = exchange_code(
        app_id="1",
        app_secret="s",
        redirect_uri="https://e.com/",
        code="c",
        client=graph,
    )

    assert token.access_token == "short"
    assert token.expires_in == 3600


def test_a_short_token_becomes_a_long_one() -> None:
    graph = client_returning(
        httpx.Response(200, json={"access_token": "long", "expires_in": 5_184_000})
    )

    token = exchange_for_long_lived(
        app_id="1", app_secret="s", token="short", client=graph
    )

    assert token.access_token == "long"
    assert token.expires_in == 5_184_000


def test_the_exchange_uses_metas_grant_type() -> None:
    """Without fb_exchange_token this silently returns the same short token."""
    seen: list[httpx.Request] = []
    graph = client_returning(
        httpx.Response(200, json={"access_token": "long"}), capture=seen
    )

    exchange_for_long_lived(app_id="1", app_secret="s", token="short", client=graph)

    assert "grant_type=fb_exchange_token" in str(seen[0].url)


def test_a_token_never_prints_itself() -> None:
    """These objects end up in tracebacks and Sentry events."""
    graph = client_returning(httpx.Response(200, json={"access_token": "secret-token"}))

    token = exchange_code(
        app_id="1",
        app_secret="s",
        redirect_uri="https://e.com/",
        code="c",
        client=graph,
    )

    assert "secret-token" not in repr(token)
    assert "secret-token" not in str(token)


# --- Inspection ----------------------------------------------------------
def test_inspect_reads_what_the_token_still_is() -> None:
    graph = client_returning(
        httpx.Response(
            200,
            json={
                "data": {
                    "app_id": "123",
                    "user_id": "999",
                    "is_valid": True,
                    "scopes": ["ads_management", "leads_retrieval"],
                    "expires_at": 1_800_000_000,
                }
            },
        )
    )

    info = inspect_token(app_id="123", app_secret="s", token="t", client=graph)

    assert info.is_valid is True
    assert info.user_id == "999"
    assert "leads_retrieval" in info.scopes
    assert info.expires_at is not None
    assert info.expires_at.year == 2027


def test_a_never_expiring_token_has_no_date() -> None:
    """Meta sends 0, which must not be read as 1970."""
    graph = client_returning(
        httpx.Response(200, json={"data": {"is_valid": True, "expires_at": 0}})
    )

    info = inspect_token(app_id="1", app_secret="s", token="t", client=graph)

    assert info.expires_at is None


def test_a_revoked_token_reports_itself_invalid() -> None:
    graph = client_returning(httpx.Response(200, json={"data": {"is_valid": False}}))

    info = inspect_token(app_id="1", app_secret="s", token="t", client=graph)

    assert info.is_valid is False


# --- Who the token belongs to --------------------------------------------
def test_the_person_behind_a_token_is_named() -> None:
    seen: list[httpx.Request] = []
    graph = client_returning(
        httpx.Response(200, json={"id": "999", "name": "Aziz Karimov"}), capture=seen
    )

    person = describe_person(token="t", client=graph)

    assert person.id == "999"
    assert person.name == "Aziz Karimov"
    assert seen[0].url.path.endswith("/me")
    assert seen[0].url.params["fields"] == "id,name"


def test_a_profile_meta_does_not_name_is_blank_rather_than_an_error() -> None:
    graph = client_returning(httpx.Response(200, json={"id": "999"}))

    assert describe_person(token="t", client=graph).name == ""


# --- Discovery -----------------------------------------------------------
def test_ad_accounts_come_back_with_the_fields_that_matter() -> None:
    """Currency and timezone decide how every later number is read."""
    graph = client_returning(
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "act_1",
                        "name": "Osh Markazi",
                        "currency": "USD",
                        "timezone_name": "Asia/Tashkent",
                        "account_status": 1,
                    }
                ]
            },
        )
    )

    accounts = list_ad_accounts(token="t", client=graph)

    assert accounts[0].currency == "USD"
    assert accounts[0].timezone_name == "Asia/Tashkent"
    assert accounts[0].is_usable is True


@pytest.mark.parametrize(
    "status",
    [pytest.param(2, id="disabled"), pytest.param(101, id="closed")],
)
def test_an_unusable_account_says_so(status: int) -> None:
    """Offering a closed account produces a campaign that never delivers."""
    graph = client_returning(
        httpx.Response(200, json={"data": [{"id": "act_1", "account_status": status}]})
    )

    assert list_ad_accounts(token="t", client=graph)[0].is_usable is False


def test_a_new_meta_field_does_not_break_the_connection() -> None:
    """Meta adds fields without announcing it."""
    graph = client_returning(
        httpx.Response(
            200, json={"data": [{"id": "act_1", "brand_new_field": "surprise"}]}
        )
    )

    assert list_ad_accounts(token="t", client=graph)[0].id == "act_1"


def client_by_path(routes: dict[str, httpx.Response]) -> GraphClient:
    """A client that answers on what was asked for, not on call order.

    The account sweep reads four different edges and a queue would pin the
    order they happen to be read in. What these tests are about is which
    lists get merged, so the transport is keyed on the path.

    An unlisted path answers an empty page, which is what Meta sends for a
    business with nothing on that edge.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        for path, response in routes.items():
            if path in request.url.path:
                return response
        return httpx.Response(200, json={"data": []})

    return GraphClient(
        token="test-token", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_an_account_only_the_business_holds_is_still_found() -> None:
    """The bug this sweep exists for.

    An ad account made inside a Business Manager belongs to the business.
    Somebody who administers that business spends from it every day and
    never got a personal role on it, so ``/me/adaccounts`` answers with
    nothing - and without this sweep the connect screen tells them they
    have no ad account while it sits in front of them in Ads Manager.
    """
    graph = client_by_path(
        {
            "me/adaccounts": httpx.Response(200, json={"data": []}),
            "me/businesses": httpx.Response(200, json={"data": [{"id": "biz_1"}]}),
            "owned_ad_accounts": httpx.Response(
                200, json={"data": [{"id": "act_9", "name": "Osh Markazi"}]}
            ),
        }
    )

    accounts = list_ad_accounts(token="t", client=graph)

    assert [account.id for account in accounts] == ["act_9"]


def test_an_agency_account_shared_with_the_business_is_found_too() -> None:
    """Everything an advertiser working through an agency has is on the
    ``client`` edge, and nothing of theirs is on the ``owned`` one."""
    graph = client_by_path(
        {
            "me/businesses": httpx.Response(200, json={"data": [{"id": "biz_1"}]}),
            "client_ad_accounts": httpx.Response(200, json={"data": [{"id": "act_7"}]}),
        }
    )

    assert [account.id for account in list_ad_accounts(token="t", client=graph)] == [
        "act_7"
    ]


def test_the_same_account_on_two_edges_is_listed_once() -> None:
    """The three lists overlap for anybody who has both kinds of access,
    and a picker offering one account twice reads as our bug."""
    same = httpx.Response(200, json={"data": [{"id": "act_1", "name": "Osh"}]})
    graph = client_by_path(
        {
            "me/adaccounts": same,
            "me/businesses": httpx.Response(200, json={"data": [{"id": "biz_1"}]}),
            "owned_ad_accounts": same,
            "client_ad_accounts": same,
        }
    )

    assert [account.id for account in list_ad_accounts(token="t", client=graph)] == [
        "act_1"
    ]


def test_a_refused_business_list_does_not_empty_the_picker() -> None:
    """A token issued before ``business_management`` was asked for cannot
    list businesses at all. Raising here would take away the accounts the
    personal edge did find - the same failure in a new place."""
    graph = client_by_path(
        {
            "me/adaccounts": httpx.Response(200, json={"data": [{"id": "act_1"}]}),
            "me/businesses": error_body(200, "requires business_management"),
        }
    )

    assert [account.id for account in list_ad_accounts(token="t", client=graph)] == [
        "act_1"
    ]


def test_one_refused_business_edge_does_not_lose_the_other() -> None:
    """An analyst on somebody else's business is refused its client list
    and answered its owned one, and both happen on the same sweep."""
    graph = client_by_path(
        {
            "me/businesses": httpx.Response(200, json={"data": [{"id": "biz_1"}]}),
            "owned_ad_accounts": httpx.Response(200, json={"data": [{"id": "act_4"}]}),
            "client_ad_accounts": error_body(200, "permissions error"),
        }
    )

    assert [account.id for account in list_ad_accounts(token="t", client=graph)] == [
        "act_4"
    ]


def test_more_businesses_than_the_ceiling_still_sweeps_the_ones_it_read() -> None:
    """The list is asked for one bounded page, so a ``next`` cursor is an
    expected answer rather than a failure. ``get_all`` would refuse the
    truncated list and leave the sweep empty - for the one reader with
    enough businesses to need it most."""
    graph = client_by_path(
        {
            "me/adaccounts": httpx.Response(200, json={"data": []}),
            "me/businesses": httpx.Response(
                200,
                json={
                    "data": [{"id": "biz_1"}],
                    "paging": {"next": "https://graph.facebook.com/v26.0/next"},
                },
            ),
            "owned_ad_accounts": httpx.Response(200, json={"data": [{"id": "act_3"}]}),
        }
    )

    assert [account.id for account in list_ad_accounts(token="t", client=graph)] == [
        "act_3"
    ]


def test_a_business_row_meta_sent_without_an_id_is_skipped() -> None:
    graph = client_by_path(
        {
            "me/adaccounts": httpx.Response(200, json={"data": [{"id": "act_1"}]}),
            "me/businesses": httpx.Response(200, json={"data": [{"name": "nameless"}]}),
        }
    )

    assert [account.id for account in list_ad_accounts(token="t", client=graph)] == [
        "act_1"
    ]


def test_an_account_row_with_no_id_is_still_refused_by_name() -> None:
    """Deduping keys on the id, and a row without one must reach the DTO
    rather than vanish into the merge: "Meta sent a shape we do not know"
    and "one account fewer" are not allowed to look alike."""
    graph = client_by_path(
        {"me/adaccounts": httpx.Response(200, json={"data": [{"name": "no id"}]})}
    )

    with pytest.raises(MetaAPIError, match="id"):
        list_ad_accounts(token="t", client=graph)


def test_pages_come_back_with_their_own_tokens() -> None:
    """Asking per page later is slower and gives the user token time to die."""
    graph = client_returning(
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "9",
                        "name": "Osh",
                        "access_token": "page-token",
                        "tasks": ["MANAGE", "ADVERTISE"],
                    }
                ]
            },
        )
    )

    pages = list_pages(token="t", client=graph)

    assert pages[0].access_token == "page-token"
    assert pages[0].may_manage is True


def test_a_page_without_manage_cannot_subscribe() -> None:
    """It would list fine and then fail at subscribe time, looking like our bug."""
    graph = client_returning(
        httpx.Response(200, json={"data": [{"id": "9", "tasks": ["ANALYZE"]}]})
    )

    assert list_pages(token="t", client=graph)[0].may_manage is False


def test_the_lead_terms_are_asked_for_with_the_page() -> None:
    """One field on a list already being fetched, and the difference
    between a refusal at the ad set - 100/1815089, one call after a lead
    form has been created and can never be deleted - and a sentence on the
    connect screen."""
    seen: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json={"data": []}), capture=seen)

    list_pages(token="t", client=graph)

    assert "leadgen_tos_accepted" in str(seen[0].url)


def test_a_page_says_whether_its_lead_terms_are_agreed_to() -> None:
    graph = client_returning(
        httpx.Response(200, json={"data": [{"id": "9", "leadgen_tos_accepted": False}]})
    )

    assert list_pages(token="t", client=graph)[0].leadgen_tos_accepted is False


def test_a_page_meta_said_nothing_about_is_not_a_page_that_said_no() -> None:
    """Three states, not two. A page fetched before this field was asked
    for holds ``None``, and reading that as a refusal would block every
    launch of every account connected until now."""
    graph = client_returning(httpx.Response(200, json={"data": [{"id": "9"}]}))

    assert list_pages(token="t", client=graph)[0].leadgen_tos_accepted is None


@pytest.mark.parametrize(
    ("tasks", "allowed"),
    [
        pytest.param(["ADVERTISE"], True, id="advertise"),
        pytest.param(["MANAGE"], True, id="manage-implies-it"),
        pytest.param(["ANALYZE", "MODERATE"], False, id="statistics-only"),
        pytest.param([], False, id="nothing-said"),
    ],
)
def test_the_roles_that_may_run_ads_from_a_page(
    tasks: list[str], allowed: bool
) -> None:
    """An empty list answers ``False`` here on purpose. Whether "Meta was
    never asked" counts as permission is the caller's decision and not this
    function's - and both callers treat it as permission."""
    assert may_advertise(tasks) is allowed


def test_a_page_never_prints_its_token() -> None:
    graph = client_returning(
        httpx.Response(200, json={"data": [{"id": "9", "access_token": "page-secret"}]})
    )

    page = list_pages(token="t", client=graph)[0]

    assert "page-secret" not in repr(page)


def test_a_borrowed_client_survives_discovery() -> None:
    graph = client_returning(httpx.Response(200, json={"data": []}))

    list_ad_accounts(token="t", client=graph)
    list_pages(token="t", client=graph)

    assert graph.get("me") == {"data": []}


# --- What a token turned out to carry ------------------------------------
def test_a_narrow_grant_names_what_is_absent() -> None:
    """Meta lets somebody untick a box on the consent screen and issues a
    token that works for everything else."""
    absent = missing(["ads_management", "ads_read"])

    assert "pages_manage_ads" in absent
    assert "ads_management" not in absent


def test_a_full_grant_is_missing_nothing() -> None:
    assert missing(list(DEFAULT_SCOPES)) == ()


def test_an_optional_permission_never_refuses_a_launch() -> None:
    """The reason ``REQUIRED_SCOPES`` exists at all.

    Every caller of ``missing`` turns a non-empty answer into a blocked
    campaign. Listing ``instagram_basic`` among the required would have
    refused every launch on every connection made before it was asked for
    - for a permission no creation sequence touches.
    """
    assert missing(list(REQUIRED_SCOPES)) == ()
    for scope in OPTIONAL_SCOPES:
        assert scope not in missing(list(REQUIRED_SCOPES))


def test_a_permission_this_token_carries_is_held() -> None:
    assert holds(["ads_management", "instagram_basic"], "instagram_basic")


def test_a_permission_left_unticked_is_not_held() -> None:
    """A narrow token is what somebody gets for unticking one box, and the
    screen that reads this draws an empty grid rather than a refusal."""
    assert not holds(list(REQUIRED_SCOPES), "instagram_basic")


def test_nothing_recorded_counts_as_held() -> None:
    """Same rule as ``missing`` and pointing the same way: a connection
    Meta has not been asked about is an unknown, and the cost of guessing
    wrong is a logged provider error rather than a screen taken away."""
    assert holds([], "instagram_basic")


def test_nothing_recorded_is_not_the_same_as_nothing_granted() -> None:
    """A connection made before scopes were recorded has none stored, and
    reading that as a refusal would lock out every account that works."""
    assert missing([]) == ()


def test_whitespace_does_not_hide_a_permission() -> None:
    """The list arrives from a JSON body and is stored in an array column
    somebody can edit in the admin."""
    assert "ads_management" not in missing([" ads_management "])


# --- Handing the permissions back ---------------------------------------
def test_revoking_deletes_every_permission_at_once() -> None:
    """No permission named means all of them, which is what erasing is."""
    seen: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json={"success": True}), capture=seen)

    assert revoke_access(user_id="7", token="t", client=graph) is True
    assert seen[0].method == "DELETE"
    assert seen[0].url.path.endswith("/7/permissions")
    assert "permission=" not in str(seen[0].url)


def test_a_refused_revoke_is_a_false_and_not_an_exception() -> None:
    """The caller is about to destroy the token either way."""
    graph = client_returning(httpx.Response(200, json={"success": False}))

    assert revoke_access(user_id="7", token="t", client=graph) is False


def test_a_body_without_success_reads_as_refused() -> None:
    """Meta answers some deletes with an empty object; absent is not yes."""
    graph = client_returning(httpx.Response(200, json={}))

    assert revoke_access(user_id="7", token="t", client=graph) is False
