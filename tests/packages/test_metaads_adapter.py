"""The translation layer: Meta's vocabulary in, the domain's out.

This is where the abstraction is either real or decorative. Two things are
pinned here and both would be invisible until the day a second provider is
added: that no Meta status reaches the domain unmapped, and that no Meta
error class escapes as itself.
"""

from unittest.mock import patch

import httpx
import pytest
from adskit import (
    AudiencePort,
    CampaignControlPort,
    ExternalRef,
    LeadSourcePort,
    MetricsPort,
)
from adskit.dto import RetiredOptionDTO
from adskit.errors import (
    AccountActionRequired,
    AuthFailed,
    BidStrategyRefused,
    BudgetTooLow,
    InvalidRequest,
    LeadFormPrivacyMissing,
    LocationNotRecognized,
    LocationsOverlap,
    MediaTooLarge,
    NotFound,
    PaymentMethodMissing,
    PermissionDenied,
    RateLimited,
    TargetingOptionRetired,
    TemporaryFailure,
    TermsNotAccepted,
)
from adskit.refs import MinorUnits
from metaads.adapter import (
    MAX_SEARCH_FALLBACK,
    MetaAudiences,
    MetaCampaigns,
    MetaMetrics,
    bundle,
    delivery_of,
    translate_error,
)
from metaads.client import GraphClient
from metaads.dto import AdAccountDTO
from metaads.errors import (
    MetaAPIError,
    MetaAuthError,
    MetaPayloadTooLarge,
    MetaTemporaryError,
    RateLimitApproaching,
)
from metaads.parsing import parsed, parsed_all

from tests.packages.test_metaads_campaigns import AD, ADSET, CAMPAIGN

ACCOUNT = ExternalRef(provider="meta", level="account", id="act_1")


def answering(payload: dict) -> GraphClient:
    return GraphClient(
        token="t",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ),
    )


# --- Delivery ------------------------------------------------------------
@pytest.mark.parametrize(
    ("effective_status", "expected"),
    [
        pytest.param("ACTIVE", "active", id="running"),
        pytest.param("PAUSED", "paused", id="switched-off"),
        # The two that describe the parent, and they keep their own word.
        # This ad set's switch is on; telling somebody to switch it on
        # sends them to a control already in the position they would move
        # it to, and an undo would then switch off what they never switched
        # off. See ``adskit.refs.Delivery``.
        pytest.param("CAMPAIGN_PAUSED", "paused_above", id="parent-paused"),
        pytest.param("ADSET_PAUSED", "paused_above", id="grandparent-paused"),
        pytest.param("PENDING_REVIEW", "pending", id="under-review"),
        pytest.param("PENDING_BILLING_INFO", "billing", id="no-card"),
        pytest.param("DISAPPROVED", "rejected", id="refused"),
        pytest.param("WITH_ISSUES", "rejected", id="needs-attention"),
        pytest.param("COMPLETED", "finished", id="ran-its-course"),
        pytest.param("ARCHIVED", "finished", id="put-away"),
    ],
)
def test_metas_status_becomes_a_domain_word(
    effective_status: str, expected: str
) -> None:
    assert delivery_of(effective_status) == expected


def test_a_status_meta_invents_next_year_is_unknown_not_active() -> None:
    """A wrong guess tells somebody their ads are fine when they are not."""
    assert delivery_of("SOME_NEW_STATE") == "unknown"


# --- Errors --------------------------------------------------------------
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        pytest.param(MetaAuthError("gone", code=190), AuthFailed, id="bad-token"),
        pytest.param(
            MetaAuthError("no perm", code=200), PermissionDenied, id="missing-scope"
        ),
        pytest.param(
            RateLimitApproaching("slow down", code=4), RateLimited, id="rate-limit"
        ),
        pytest.param(MetaTemporaryError("5xx"), TemporaryFailure, id="transient"),
        pytest.param(MetaAPIError("gone", code=803), NotFound, id="missing-object"),
        pytest.param(MetaAPIError("bad", code=2635), InvalidRequest, id="our-bug"),
        # 100 is "Invalid parameter": a refused value, not a missing object.
        pytest.param(MetaAPIError("bad", code=100), InvalidRequest, id="bad-value"),
        # The Zuho refusal: a pin in open sea. Filed as a rejected payload
        # it told the owner to rewrite the ad; the fix is the geography.
        pytest.param(
            MetaAPIError("where", code=100, subcode=1487851),
            LocationNotRecognized,
            id="unknown-place",
        ),
        # A city beside the region it lies in. Both are real places, so this
        # is not the unknown-place line above: one of the two has to go.
        pytest.param(
            MetaAPIError("conflict", code=100, subcode=1487756),
            LocationsOverlap,
            id="overlapping-places",
        ),
        # HTTP 413 with an empty body - the only thing known is the size.
        pytest.param(
            MetaPayloadTooLarge("HTTP 413"), MediaTooLarge, id="file-too-large"
        ),
        # Code 31 is a family, not a reason: "this request requires the
        # user to take a pending action". The subcode is what says which
        # action, and 3858385 is the security hold that stops every write
        # to the account until its owner confirms themselves in Meta's own
        # console. Without this line it arrives as a bad token and the
        # screen says "reconnect", which does nothing.
        pytest.param(
            MetaAuthError("held", code=31, subcode=3858385),
            AccountActionRequired,
            id="account-held",
        ),
        pytest.param(
            MetaAuthError("pending", code=31), AuthFailed, id="pending-but-unnamed"
        ),
    ],
)
def test_a_meta_failure_arrives_as_the_domains_own(
    failure: MetaAPIError, expected: type
) -> None:
    """A service catching `code == 190` breaks the day Google is added."""
    assert isinstance(translate_error(failure), expected)


def test_only_the_transient_families_are_marked_retryable() -> None:
    """Retrying a permission error burns the budget the retries need."""
    assert translate_error(MetaTemporaryError("5xx")).retryable is True
    assert translate_error(MetaAuthError("gone", code=190)).retryable is False


@pytest.mark.parametrize("code", [32, 368, 80000, 80004, 80014])
def test_a_limit_from_the_wire_reaches_the_domain_as_a_limit(code: int) -> None:
    """From Meta's body to the domain's class, the whole way.

    A 368 filed as ``AuthFailed`` marked the connection unusable and showed
    "reconnect" for a block that lifts by itself. The business use case
    codes filed as ``InvalidRequest`` read as a bug in our own request.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "x", "code": code}})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(refuse))
    )
    with pytest.raises(MetaAPIError) as caught:
        graph.get("me")

    translated = translate_error(caught.value)
    assert isinstance(translated, RateLimited)
    assert translated.retryable is True


def test_the_provider_code_survives_for_the_log() -> None:
    assert translate_error(MetaAuthError("gone", code=190)).code == "190"


def test_a_failure_mid_call_is_translated_not_leaked() -> None:
    """The whole point of the session wrapper: nothing raw escapes."""
    graph = GraphClient(
        token="t",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(400, json={"error": {"code": 190}})
            )
        ),
    )

    with (
        patch("metaads.adapter.GraphClient", return_value=graph),
        pytest.raises(AuthFailed),
    ):
        MetaCampaigns().list_campaigns(account=ACCOUNT, token="t")


# --- Translation ---------------------------------------------------------
def test_a_campaign_crosses_the_boundary_as_a_domain_object() -> None:
    with patch(
        "metaads.adapter.GraphClient", return_value=answering({"data": [CAMPAIGN]})
    ):
        campaigns = MetaCampaigns().list_campaigns(account=ACCOUNT, token="t")

    campaign = campaigns[0]
    assert campaign.ref == ExternalRef(provider="meta", level="campaign", id="120210")
    assert campaign.delivery == "active"
    assert campaign.daily_budget_minor == 1000
    assert campaign.objective_raw == "OUTCOME_LEADS"


def test_a_campaign_carries_no_currency_because_meta_sends_none() -> None:
    """Empty rather than guessed. The caller has the account and knows."""
    with patch(
        "metaads.adapter.GraphClient", return_value=answering({"data": [CAMPAIGN]})
    ):
        campaigns = MetaCampaigns().list_campaigns(account=ACCOUNT, token="t")

    assert campaigns[0].currency == ""


def test_an_ad_set_knows_which_campaign_it_belongs_to() -> None:
    with patch(
        "metaads.adapter.GraphClient", return_value=answering({"data": [ADSET]})
    ):
        adsets = MetaCampaigns().list_adsets(account=ACCOUNT, token="t")

    assert adsets[0].campaign_ref.id == "120210"
    assert adsets[0].campaign_ref.level == "campaign"


def test_learning_is_decided_here_and_not_by_the_caller() -> None:
    """A boolean, so no screen has to know Meta's several learning values."""
    with patch(
        "metaads.adapter.GraphClient", return_value=answering({"data": [ADSET]})
    ):
        adsets = MetaCampaigns().list_adsets(account=ACCOUNT, token="t")

    assert adsets[0].is_learning is True
    assert adsets[0].learning_status == "LEARNING"


def test_the_audiences_an_ad_set_is_aimed_at_survive_the_read() -> None:
    """**No column and no parser.** The targeting spec is mirrored whole,
    so whichever audiences the provider echoes back are in the mirror and
    in what the agent reads - "this ad set is aimed at people who resemble
    the customers" is answerable without anything new.

    Whether the provider echoes these keys at all is answered where every
    creation compares what went out against what came back.
    """
    payload = {
        **ADSET,
        "targeting": {
            "age_min": 25,
            "custom_audiences": [{"id": "6001"}],
            "excluded_custom_audiences": [{"id": "6002"}],
        },
    }

    with patch(
        "metaads.adapter.GraphClient", return_value=answering({"data": [payload]})
    ):
        adsets = MetaCampaigns().list_adsets(account=ACCOUNT, token="t")

    assert adsets[0].targeting_raw["custom_audiences"] == [{"id": "6001"}]
    assert adsets[0].targeting_raw["excluded_custom_audiences"] == [{"id": "6002"}]


def test_an_ad_set_that_gave_up_learning_is_not_protected() -> None:
    """LEARNING_LIMITED will never finish. It is exactly what to change."""
    payload = {**ADSET, "learning_stage_info": {"status": "LEARNING_LIMITED"}}

    with patch(
        "metaads.adapter.GraphClient", return_value=answering({"data": [payload]})
    ):
        adsets = MetaCampaigns().list_adsets(account=ACCOUNT, token="t")

    assert adsets[0].is_learning is False


def test_an_ad_carries_its_lead_form_across() -> None:
    with patch("metaads.adapter.GraphClient", return_value=answering({"data": [AD]})):
        ads = MetaCampaigns().list_ads(account=ACCOUNT, token="t")

    assert ads[0].lead_form_external_id == "777"
    assert ads[0].delivery == "rejected"


def test_a_status_read_asks_for_the_learning_stage_only_for_ad_sets() -> None:
    """Asking a campaign for one is an error, not an empty answer."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ACTIVE"})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    ref = ExternalRef(provider="meta", level="campaign", id="1")

    with patch("metaads.adapter.GraphClient", return_value=graph):
        MetaCampaigns().get_status(ref=ref, token="t")

    assert "learning_stage_info" not in str(seen[0].url)


# --- Interests -----------------------------------------------------------
VALID_INTEREST = {
    "id": "6003123",
    "name": "Restaurants",
    "valid": True,
    "audience_size_lower_bound": 900_000,
    "audience_size_upper_bound": 1_100_000,
    "path": ["Interests", "Food and drink", "Restaurants"],
}


def test_a_recognised_name_comes_back_as_something_targetable() -> None:
    """The whole point: a word is not targeting until Meta gives it an id."""
    with patch(
        "metaads.adapter.GraphClient",
        return_value=answering({"data": [VALID_INTEREST]}),
    ):
        found = MetaAudiences().find_interests(names=["Restaurants"], token="t")

    assert found[0].ref == ExternalRef(provider="meta", level="interest", id="6003123")
    assert found[0].name == "Restaurants"
    assert found[0].path == ("Interests", "Food and drink", "Restaurants")


def test_the_size_stays_a_range_because_meta_does_not_know_either() -> None:
    """One number here becomes one number on a screen somebody budgets by."""
    with patch(
        "metaads.adapter.GraphClient",
        return_value=answering({"data": [VALID_INTEREST]}),
    ):
        found = MetaAudiences().find_interests(names=["Restaurants"], token="t")

    assert found[0].audience_lower == 900_000
    assert found[0].audience_upper == 1_100_000


def test_an_account_still_on_the_old_field_shows_a_size_not_a_zero() -> None:
    """Meta replaced audience_size with bounds and still sends the old one."""
    row = {"id": "6003", "name": "Coffee", "valid": True, "audience_size": 4_200}

    with patch("metaads.adapter.GraphClient", return_value=answering({"data": [row]})):
        found = MetaAudiences().find_interests(names=["Coffee"], token="t")

    assert found[0].audience_lower == 4_200
    assert found[0].audience_upper == 4_200


def test_a_name_meta_does_not_have_is_simply_absent() -> None:
    """Not an error. "We have no such interest" is a real answer, and the
    caller drops the name with a reason rather than retrying."""
    payload = {"data": [VALID_INTEREST, {"name": "Sartaroshxona", "valid": False}]}

    with patch("metaads.adapter.GraphClient", return_value=answering(payload)):
        found = MetaAudiences().find_interests(
            names=["Restaurants", "Sartaroshxona"], token="t"
        )

    assert [item.name for item in found] == ["Restaurants"]


def test_a_valid_name_without_an_id_is_dropped_too() -> None:
    """Targeting is built from ids. A name Meta declined to identify would
    be dropped one layer later, with less to say about why."""
    payload = {"data": [{"name": "Coffee", "valid": True}]}

    with patch("metaads.adapter.GraphClient", return_value=answering(payload)):
        assert MetaAudiences().find_interests(names=["Coffee"], token="t") == []


# --- The second pass, when the bulk check leaves no id -------------------
def by_search_type(
    *, valid: dict, search: dict
) -> tuple[GraphClient, list[httpx.Request]]:
    """Answer the two endpoints differently, because they are two questions.

    ``adinterestvalid`` says whether a name exists; ``adinterest`` says
    which interest it is. A stub that answers both the same way cannot show
    the difference the fallback exists for.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = valid if "adinterestvalid" in str(request.url) else search
        return httpx.Response(200, json=body)

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return graph, seen


def test_a_name_the_bulk_check_could_not_identify_is_looked_up_again() -> None:
    """The failure this exists for: Meta agrees the name is real and hands
    back no id, so a perfectly ordinary interest is reported as unknown and
    the launch has nothing to target."""
    graph, _ = by_search_type(
        valid={"data": [{"name": "Education", "valid": True}]},
        search={"data": [{"id": "6003", "name": "Education"}]},
    )

    with patch("metaads.adapter.GraphClient", return_value=graph):
        found = MetaAudiences().find_interests(names=["Education"], token="t")

    assert [item.ref.id for item in found] == ["6003"]


def test_the_second_pass_matches_across_capitalisation() -> None:
    """Providers answer with their own casing. Treating that as a miss is
    what drops half of every list."""
    graph, _ = by_search_type(
        valid={"data": []},
        search={"data": [{"id": "6003", "name": "Small Business"}]},
    )

    with patch("metaads.adapter.GraphClient", return_value=graph):
        found = MetaAudiences().find_interests(names=["small business"], token="t")

    assert [item.ref.id for item in found] == ["6003"]


def test_the_second_pass_refuses_a_near_miss() -> None:
    """Meta ranks by relevance, so the top row is always *something*. Taking
    it would mean an owner who asked for one audience getting another and
    never being told."""
    graph, _ = by_search_type(
        valid={"data": []},
        search={"data": [{"id": "6003", "name": "Higher education"}]},
    )

    with patch("metaads.adapter.GraphClient", return_value=graph):
        found = MetaAudiences().find_interests(names=["Education"], token="t")

    assert found == []


def test_a_name_the_bulk_check_resolved_is_not_looked_up_twice() -> None:
    graph, seen = by_search_type(valid={"data": [VALID_INTEREST]}, search={"data": []})

    with patch("metaads.adapter.GraphClient", return_value=graph):
        MetaAudiences().find_interests(names=["Restaurants"], token="t")

    assert len(seen) == 1


def test_the_second_pass_is_capped() -> None:
    """One call per unresolved name, against the account's own budget."""
    names = [f"Name {index}" for index in range(20)]
    graph, seen = by_search_type(valid={"data": []}, search={"data": []})

    with patch("metaads.adapter.GraphClient", return_value=graph):
        MetaAudiences().find_interests(names=names, token="t")

    assert len(seen) == 1 + MAX_SEARCH_FALLBACK


def test_the_catalogue_is_asked_in_the_language_it_is_queried_in() -> None:
    """Meta localises interest *names* to the account and keeps the ids.

    A Russian account answers "Образование" where an English one answers
    "Education" - same interest, same id, different word - and every query
    this project sends is English by construction. Without the locale the
    two sides speak different languages, and an account answering in
    another one drops every interest Meta has translated while keeping the
    ones it has not.
    """
    graph, seen = by_search_type(valid={"data": []}, search={"data": []})

    with patch("metaads.adapter.GraphClient", return_value=graph):
        MetaAudiences().find_interests(names=["Education"], token="t")

    assert all("locale=en_US" in str(request.url) for request in seen)


def test_the_bulk_check_asks_for_the_id_it_needs() -> None:
    """Its default answer is a name and a boolean, and targeting is built
    from ids."""
    graph, seen = by_search_type(valid={"data": []}, search={"data": []})

    with patch("metaads.adapter.GraphClient", return_value=graph):
        MetaAudiences().find_interests(names=["Coffee"], token="t")

    assert "fields=" in str(seen[0].url)


def test_an_empty_list_never_reaches_meta() -> None:
    """Meta errors on an empty interest_list, and the question is pointless."""
    with patch("metaads.adapter.GraphClient", side_effect=AssertionError("called")):
        assert MetaAudiences().find_interests(names=[], token="t") == []


def test_an_interest_failure_arrives_as_the_domains_own() -> None:
    graph = GraphClient(
        token="t",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(400, json={"error": {"code": 190}})
            )
        ),
    )

    with (
        patch("metaads.adapter.GraphClient", return_value=graph),
        pytest.raises(AuthFailed),
    ):
        MetaAudiences().find_interests(names=["Restaurants"], token="t")


# --- Reach ---------------------------------------------------------------
def test_a_reach_estimate_comes_back_as_a_range() -> None:
    payload = {
        "data": [
            {
                "estimate_mau_lower_bound": 120_000,
                "estimate_mau_upper_bound": 180_000,
                "estimate_ready": True,
            }
        ]
    }

    with patch("metaads.adapter.GraphClient", return_value=answering(payload)):
        reach = MetaAudiences().estimate_reach(
            account=ACCOUNT,
            targeting={"age_min": 25},
            optimization_goal="QUALITY_CALL",
            token="t",
        )

    assert (reach.lower, reach.upper) == (120_000, 180_000)
    assert reach.ready is True


def test_an_estimate_meta_has_not_finished_says_so_instead_of_zero() -> None:
    """Zeroes with estimate_ready false mean "not yet", and showing them as
    a reach of nobody sends an owner off to widen an audience that was
    never narrow."""
    payload = {"data": [{"estimate_ready": False}]}

    with patch("metaads.adapter.GraphClient", return_value=answering(payload)):
        reach = MetaAudiences().estimate_reach(
            account=ACCOUNT,
            targeting={},
            optimization_goal="QUALITY_CALL",
            token="t",
        )

    assert reach.ready is False


def test_meta_answering_nothing_at_all_is_not_a_reach_of_zero() -> None:
    with patch("metaads.adapter.GraphClient", return_value=answering({"data": []})):
        reach = MetaAudiences().estimate_reach(
            account=ACCOUNT, targeting={}, optimization_goal="REACH", token="t"
        )

    assert reach.ready is False
    assert reach.lower == 0


def test_a_negative_bound_is_a_refusal_rather_than_a_number() -> None:
    """Meta stopped sizing specs that name certain custom audiences - a
    customer file matched on more than one key among them - and says so by
    answering ``-1``: *"The API returns a '-1' value as an audience size
    estimate."*

    This product uploads exactly such a file, so the case is ordinary. A
    ``-1`` carried through as an integer becomes "about -1 people" on
    somebody's review screen.
    """
    payload = {
        "data": [
            {
                "estimate_mau_lower_bound": -1,
                "estimate_mau_upper_bound": -1,
                "estimate_ready": True,
            }
        ]
    }

    with patch("metaads.adapter.GraphClient", return_value=answering(payload)):
        reach = MetaAudiences().estimate_reach(
            account=ACCOUNT,
            targeting={"custom_audiences": [{"id": "1"}]},
            optimization_goal="LEAD_GENERATION",
            token="t",
        )

    assert reach.available is False
    assert (reach.lower, reach.upper) == (0, 0)


def test_not_yet_and_not_ever_are_different_answers() -> None:
    """Waiting fixes the first and will never fix the second, so a caller
    that treated both as a zero would either nag or mislead."""
    with patch(
        "metaads.adapter.GraphClient",
        return_value=answering({"data": [{"estimate_ready": False}]}),
    ):
        waiting = MetaAudiences().estimate_reach(
            account=ACCOUNT, targeting={}, optimization_goal="REACH", token="t"
        )

    assert (waiting.ready, waiting.available) == (False, True)


def test_a_rehearsed_audience_change_reaches_nobody() -> None:
    """``dry_run`` is checked one line above the HTTP call, not by callers.

    Every write in this package defaults to True and this is the one that
    replaces an audience wholesale - the write where an unguarded rehearsal
    would silently retarget a live campaign.
    """
    ref = ExternalRef(provider="meta", level="adset", id="1")

    result = MetaAudiences().apply(
        ref=ref, targeting={"age_min": 18}, token="t", dry_run=True
    )

    assert result.ok is True
    assert result.dry_run is True
    assert result.dropped == {}


def test_an_audience_change_reports_what_meta_quietly_dropped() -> None:
    """Meta accepts a spec, removes what it no longer recognises, and
    answers 200. The difference between what was sent and what came back is
    the only evidence, and it has to survive as far as the audit row - a
    campaign running on a narrower audience than the one that was approved
    is otherwise invisible."""
    sent = {
        "age_min": 25,
        "flexible_spec": [{"interests": [{"id": "6003", "name": "Fitness"}]}],
        "excluded_geo_locations": {"countries": ["KZ"]},
    }
    kept = {"age_min": 25, "flexible_spec": [{"interests": []}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"targeting": kept})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with patch("metaads.adapter.GraphClient", return_value=graph):
        result = MetaAudiences().apply(
            ref=ExternalRef(provider="meta", level="adset", id="1"),
            targeting=sent,
            token="t",
            dry_run=False,
        )

    assert result.ok is True
    assert result.dropped["interests"] == ["6003"]
    assert "excluded_geo_locations" in result.dropped
    assert "age_min" not in result.dropped


# --- The bundle ----------------------------------------------------------
def test_the_adapter_satisfies_the_port() -> None:
    """Checked against the protocol, never against a base class."""
    assert isinstance(MetaCampaigns(), CampaignControlPort)


def test_the_audience_adapter_satisfies_its_port() -> None:
    assert isinstance(MetaAudiences(), AudiencePort)


# --- Writes --------------------------------------------------------------
CAMPAIGN_REF = ExternalRef(provider="meta", level="campaign", id="120210")
ADSET_REF = ExternalRef(provider="meta", level="adset", id="238999")


def sent(payloads: list[dict]) -> GraphClient:
    """A client that records what each write posted and answers success."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        body.pop("access_token", None)
        payloads.append(body)
        return httpx.Response(200, json={"success": True})

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


@pytest.mark.parametrize(
    ("asked", "posted"),
    [
        pytest.param("paused", "PAUSED", id="stop"),
        pytest.param("active", "ACTIVE", id="start"),
        # Case is the caller's business, not a reason to refuse.
        pytest.param("Paused", "PAUSED", id="mixed-case"),
    ],
)
def test_the_domains_word_goes_out_as_metas(asked: str, posted: str) -> None:
    """The whole point of the port. A service that had to send "ACTIVE"
    would have Meta's vocabulary written into it."""
    payloads: list[dict] = []

    with patch("metaads.adapter.GraphClient", return_value=sent(payloads)):
        result = MetaCampaigns().set_status(
            ref=CAMPAIGN_REF, status=asked, token="t", dry_run=False
        )

    assert payloads == [{"status": posted}]
    assert result.ok is True


def test_what_comes_back_is_the_domains_word_not_metas() -> None:
    """``applied`` is read by whoever asks what happened to their campaign,
    and it is stored in our own table."""
    with patch("metaads.adapter.GraphClient", return_value=sent([])):
        result = MetaCampaigns().set_status(
            ref=CAMPAIGN_REF, status="paused", token="t", dry_run=False
        )

    assert result.applied == {"status": "paused"}


@pytest.mark.parametrize(
    "status",
    [
        pytest.param("ENABLED", id="another-providers-word"),
        pytest.param("pending", id="not-a-request"),
        pytest.param("rejected", id="metas-decision"),
        pytest.param("", id="nothing"),
    ],
)
def test_a_status_nobody_can_ask_for_is_refused_before_the_call(status: str) -> None:
    """Silently doing nothing would report success for a button that did
    not work. ``ENABLED`` is Google's word for the same state and is
    refused here rather than guessed at - which is the check that will
    still mean something once there is a second adapter."""
    payloads: list[dict] = []

    with (
        patch("metaads.adapter.GraphClient", return_value=sent(payloads)),
        pytest.raises(InvalidRequest),
    ):
        MetaCampaigns().set_status(
            ref=CAMPAIGN_REF, status=status, token="t", dry_run=False
        )

    assert payloads == []


def test_a_rehearsed_status_change_never_reaches_meta() -> None:
    """``dry_run`` defaults to True on every write in this package."""
    payloads: list[dict] = []

    with patch("metaads.adapter.GraphClient", return_value=sent(payloads)):
        result = MetaCampaigns().set_status(
            ref=CAMPAIGN_REF, status="paused", token="t"
        )

    assert payloads == []
    assert result.dry_run is True
    assert result.ok is True


def test_a_budget_goes_out_in_minor_units_unconverted() -> None:
    """Stored as an integer count of the smallest unit and sent as one.
    There is no second representation to round through."""
    payloads: list[dict] = []

    with patch("metaads.adapter.GraphClient", return_value=sent(payloads)):
        result = MetaCampaigns().set_budget(
            ref=ADSET_REF,
            daily_budget_minor=MinorUnits(250_000),
            token="t",
            dry_run=False,
        )

    assert payloads == [{"daily_budget": "250000"}]
    assert result.applied == {"daily_budget_minor": 250_000}
    assert result.ref == ADSET_REF


def test_a_rehearsed_budget_change_never_reaches_meta() -> None:
    payloads: list[dict] = []

    with patch("metaads.adapter.GraphClient", return_value=sent(payloads)):
        MetaCampaigns().set_budget(
            ref=ADSET_REF, daily_budget_minor=MinorUnits(250_000), token="t"
        )

    assert payloads == []


def test_metas_budget_floor_arrives_as_the_refusal_the_owner_can_clear() -> None:
    """``100/1885272`` and nothing else in the family says so. Without the
    translation the screen tells an advertiser to change their picture."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 100,
                    "error_subcode": 1885272,
                    "message": "Invalid parameter",
                    "error_user_title": "Budget Is Too Low",
                }
            },
        )

    client = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with (
        patch("metaads.adapter.GraphClient", return_value=client),
        pytest.raises(BudgetTooLow),
    ):
        MetaCampaigns().set_budget(
            ref=ADSET_REF, daily_budget_minor=MinorUnits(1), token="t", dry_run=False
        )


@pytest.mark.parametrize(
    ("port", "protocol"),
    [
        pytest.param("metrics", MetricsPort, id="metrics"),
        pytest.param("leads", LeadSourcePort, id="leads"),
    ],
)
def test_the_ports_not_built_yet_still_fill_the_bundle(
    port: str, protocol: type
) -> None:
    """A half-built provider must fail where it is called, naming the port."""
    assert isinstance(getattr(bundle(), port), protocol)


def test_the_bundle_hands_over_the_real_audience_adapter() -> None:
    """Registered while only half of it works. The half that does is the
    half the launch flow needs, and the other half refuses by name."""
    assert isinstance(bundle().audiences, MetaAudiences)


def test_the_bundle_hands_over_the_real_metrics_adapter() -> None:
    """The last of the four."""
    assert isinstance(bundle().metrics, MetaMetrics)


def test_no_port_in_the_bundle_refuses_by_name_any_more() -> None:
    """Every one of the four is real, and what this asserts is the shape
    rather than the absence of a stub."""
    provider = bundle()

    for port in (
        provider.campaigns,
        provider.metrics,
        provider.leads,
        provider.audiences,
    ):
        assert type(port).__module__.startswith("metaads")


# --- A shape change is a failure this package owns ------------------------
def test_a_field_meta_sends_as_a_number_is_still_read() -> None:
    """``spend_cap`` comes back quoted and ``min_daily_budget``, in the same
    object, bare. Refusing the second fails the whole account list - and
    that list is read in the middle of the connect callback."""
    account = AdAccountDTO.model_validate(
        {"id": "act_1", "spend_cap": "50000", "min_daily_budget": 100}
    )

    assert account.min_daily_budget_minor == 100
    assert account.spend_cap == "50000"


def test_a_null_where_money_was_expected_is_read_as_unsaid() -> None:
    account = AdAccountDTO.model_validate({"id": "act_1", "min_daily_budget": None})

    assert account.min_daily_budget_minor == 0


def test_a_shape_that_changed_is_this_packages_error_and_names_the_field() -> None:
    """A pydantic error reaching a caller that catches MetaError is a
    traceback in whichever view happened to ask - which is how the connect
    callback becomes a blank 500."""
    with pytest.raises(MetaAPIError, match="account_status"):
        parsed(AdAccountDTO, {"id": "act_1", "account_status": "not a number"})


def test_one_bad_row_fails_the_whole_page_rather_than_vanishing() -> None:
    """A list with one row silently missing is worse than a refusal: the
    customer sees five of their six accounts and no reason to look for the
    sixth."""
    with pytest.raises(MetaAPIError):
        parsed_all(AdAccountDTO, [{"id": "act_1"}, {"name": "no id at all"}])


def test_unaccepted_lead_terms_are_their_own_failure() -> None:
    """Meta answers this with code 100 - the same code as a malformed
    targeting spec - so only the subcode separates "you must agree to
    something" from "we sent nonsense". One the owner can fix; the other
    they cannot."""
    refusal = MetaAPIError("Terms of Service Not Accepted", code=100, subcode=1815089)

    translated = translate_error(refusal)

    assert isinstance(translated, TermsNotAccepted)
    assert not translated.retryable


def test_an_ordinary_invalid_parameter_is_not_mistaken_for_it() -> None:
    refusal = MetaAPIError("Invalid parameter", code=100, subcode=2490562)

    assert not isinstance(translate_error(refusal), TermsNotAccepted)


def test_a_form_without_a_privacy_policy_is_its_own_failure() -> None:
    """100/1892142: the fix is another form, not another text or picture."""
    refusal = MetaAPIError(
        "Invalid parameter",
        code=100,
        subcode=1892142,
        user_title="This Promotion Requires a Privacy Policy",
    )

    translated = translate_error(refusal)

    assert isinstance(translated, LeadFormPrivacyMissing)
    assert translated.code == "1892142"
    assert not translated.retryable


def test_a_budget_under_the_floor_is_its_own_failure() -> None:
    """Code 100 again, so without this it lands as InvalidRequest and the
    review page renders it as "change your text or your picture". The
    advertiser can fix this one in ten seconds on a screen we already have,
    and only if somebody tells them which number is wrong."""
    refusal = MetaAPIError("Invalid parameter", code=100, subcode=1885272)

    translated = translate_error(refusal)

    assert isinstance(translated, BudgetTooLow)
    assert not translated.retryable


def test_a_budget_refusal_keeps_the_number_meta_named() -> None:
    """Meta writes the actual minimum into the advertiser-facing pair, in
    the account's own currency. Our own sentence cannot know it."""
    refusal = MetaAPIError(
        "Invalid parameter",
        code=100,
        subcode=1885272,
        user_title="Budget Is Too Low",
        user_message="The minimum daily budget for this ad set is $2.00.",
    )

    assert "$2.00" in translate_error(refusal).user_message


@pytest.mark.parametrize(
    ("subcode", "title"),
    [
        (1885204, "Optimization goal only supports autobid"),
        (2446166, "Optimization Goal Incompatible with Cost Cap"),
    ],
)
def test_a_cost_cap_the_goal_does_not_take_is_its_own_failure(
    subcode: int, title: str
) -> None:
    """Seen in production for a call and for a conversation. Code 100, so
    untranslated it tells the advertiser to change their text."""
    refusal = MetaAPIError(
        "Invalid parameter", code=100, subcode=subcode, user_title=title
    )

    translated = translate_error(refusal)

    assert isinstance(translated, BidStrategyRefused)
    assert translated.code == str(subcode)
    assert not translated.retryable


# --- A catalogue entry Meta has withdrawn --------------------------------
# Code 100 again, and the worst of the family: the dead word is in the
# audience, so nothing the advertiser changes about the ad can clear it -
# and untranslated it tells them to change their text or their picture.
# The refusal is also the only announcement there will ever be: the
# catalogue search goes on returning the entry for months.
RETIRED_MSG = (
    "Please update the targeting spec to remove them or replace them with "
    "alternative options. Relevant alternative options: "
    '[{"deprecated_interest_id":"6003337741151",'
    '"deprecated_interest_name":"Tea house",'
    '"alternative_interest_id":"6003491283786",'
    '"alternative_interest_name":"Tea"}]'
)


def a_retired_refusal(message: str = RETIRED_MSG) -> MetaAPIError:
    return MetaAPIError(
        "Invalid parameter",
        code=100,
        subcode=1487079,
        user_title="Some detailed targeting options have been combined",
        user_message=message,
    )


def test_a_withdrawn_targeting_option_is_its_own_failure() -> None:
    translated = translate_error(a_retired_refusal())

    assert isinstance(translated, TargetingOptionRetired)
    assert not translated.retryable


def test_the_refusal_carries_the_replacement_meta_named() -> None:
    """The whole reason it is a class of its own. Meta writes the mapping
    into a sentence for the advertiser and nowhere else - not into the
    catalogue, which still answers with the dead entry - so a translation
    that drops it turns a fixable campaign into an unfixable one."""
    translated = translate_error(a_retired_refusal())

    assert isinstance(translated, TargetingOptionRetired)
    assert translated.retired == (
        RetiredOptionDTO(
            retired_id="6003337741151",
            retired_name="Tea house",
            alternative_id="6003491283786",
            alternative_name="Tea",
        ),
    )


def test_an_option_withdrawn_with_no_replacement_is_still_read() -> None:
    """A real answer rather than a missing one: the option goes and nothing
    takes its seat, and a reader that required a replacement would leave
    that audience with the dead id in it."""
    message = (
        "Relevant alternative options: "
        '[{"deprecated_interest_id":"6003337741151",'
        '"deprecated_interest_name":"Tea house"}]'
    )

    translated = translate_error(a_retired_refusal(message))

    assert isinstance(translated, TargetingOptionRetired)
    assert translated.retired[0].alternative_id == ""


def test_a_refusal_with_nothing_to_read_stays_an_ordinary_one() -> None:
    """The rule is honest about its own limit. This failure is claimed only
    when the mapping can be read out of it, because the mapping is the only
    thing that makes it worth claiming."""
    refusal = MetaAPIError(
        "Invalid parameter",
        code=100,
        subcode=1487079,
        user_title="Some detailed targeting options have been combined",
        user_message="Please update the targeting spec.",
    )

    assert not isinstance(translate_error(refusal), TargetingOptionRetired)


def test_a_sentence_that_is_not_json_does_not_raise() -> None:
    """A diagnostic that throws while explaining a failure hides the
    failure it was written to explain."""
    translated = translate_error(a_retired_refusal("options: [{not json at all}]"))

    assert not isinstance(translated, TargetingOptionRetired)


def test_the_advertiser_words_survive_the_translation() -> None:
    """They are the whole reason the field exists. A domain error that
    drops them leaves the screen with nothing but "refused"."""
    failure = MetaAPIError(
        "Invalid parameter",
        code=100,
        subcode=1815316,
        user_title="Lead Ad Creative Does Not Use External URL",
        user_message="Change the URL at the creative level.",
    )

    translated = translate_error(failure)

    assert translated.user_title.startswith("Lead Ad Creative")
    assert translated.user_message == "Change the URL at the creative level."


def test_a_failure_with_nothing_to_quote_translates_cleanly() -> None:
    translated = translate_error(MetaAPIError("boom", code=2635))

    assert translated.user_title == ""
    assert translated.user_message == ""


def test_no_payment_method_is_its_own_failure() -> None:
    """``100/1359188``, seen in production on the ad itself. As a rejected
    payload the screen would send the owner to their text."""
    refusal = MetaAPIError(
        "Invalid parameter",
        code=100,
        subcode=1359188,
        user_title="No Payment Method",
    )

    translated = translate_error(refusal)

    assert isinstance(translated, PaymentMethodMissing)
    assert translated.code == "1359188"
    assert translated.user_title == "No Payment Method"


def test_the_billing_page_opens_on_one_account() -> None:
    from metaads.accounts import billing_url, owes_payment

    assert billing_url("act_55").endswith("payment_settings/?asset_id=55")
    assert owes_payment(3)
    assert not owes_payment(2)
