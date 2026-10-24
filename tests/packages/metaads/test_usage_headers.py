"""The two call budgets Meta reports, and which one runs out first.

No network: these are header shapes, and the shapes are the point. Meta
reports usage twice on every response and the two are not the same object.

* ``X-Business-Use-Case-Usage`` is keyed by ad account and holds a list per
  key. One customer's heavy night exhausts that customer.
* ``X-App-Usage`` is one flat object for the whole application. Every
  subscription spends the same figure, so it is the budget that starts to
  bind as customers are added - and left unread, the first sign of it is
  every account refused at once.

The client stops at eighty percent of either, because past the real limit
Meta blocks for minutes and that costs far more than the last fifth would
have bought.
"""

import json

import httpx
import pytest
from metaads.client import USAGE_STOP_PERCENT, GraphClient
from metaads.errors import RateLimitApproaching


def a_response(**headers: str) -> httpx.Response:
    return httpx.Response(200, headers=headers, json={})


def check(response: httpx.Response) -> None:
    GraphClient._check_usage(response)


def test_a_quiet_response_passes() -> None:
    check(a_response())


def test_the_app_wide_budget_is_read() -> None:
    """The one this deployment shares."""
    header = json.dumps({"call_count": 91, "total_cputime": 3, "total_time": 7})

    with pytest.raises(RateLimitApproaching) as caught:
        check(a_response(**{"X-App-Usage": header}))

    assert caught.value.percent == 91


def test_the_app_budget_below_the_ceiling_is_allowed() -> None:
    header = json.dumps({"call_count": USAGE_STOP_PERCENT - 1})

    check(a_response(**{"X-App-Usage": header}))


def test_the_per_account_budget_is_still_read() -> None:
    header = json.dumps({"act_1": [{"call_count": 5}, {"total_time": 88}]})

    with pytest.raises(RateLimitApproaching) as caught:
        check(a_response(**{"X-Business-Use-Case-Usage": header}))

    assert caught.value.percent == 88


def test_the_worse_of_the_two_is_the_one_that_stops_it() -> None:
    """Either budget running out refuses the call, whichever it is."""
    quiet = json.dumps({"act_1": [{"call_count": 2}]})
    loud = json.dumps({"call_count": 95})

    with pytest.raises(RateLimitApproaching) as caught:
        check(a_response(**{"X-Business-Use-Case-Usage": quiet, "X-App-Usage": loud}))

    assert caught.value.percent == 95


def test_a_header_of_the_wrong_shape_is_survived() -> None:
    """Somebody else's bug is not ours to raise on.

    A refusal here would stop a sync that Meta was perfectly willing to
    answer, which is the opposite of what the guard is for.
    """
    check(a_response(**{"X-App-Usage": "not json"}))
    check(a_response(**{"X-App-Usage": json.dumps([1, 2, 3])}))
    check(a_response(**{"X-Business-Use-Case-Usage": json.dumps({"act_1": 7})}))


def test_a_figure_sent_as_a_string_still_counts() -> None:
    """Meta has sent these as strings before now."""
    with pytest.raises(RateLimitApproaching):
        check(a_response(**{"X-App-Usage": json.dumps({"call_count": "97"})}))
