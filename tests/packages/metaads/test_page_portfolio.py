"""The portfolios a page and an ad account sit in, read from Meta."""

import httpx
from metaads.accounts import list_ad_accounts, list_pages
from metaads.client import GraphClient


def _graph(handler) -> GraphClient:  # type: ignore[no-untyped-def]
    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_pages_carry_their_owner_and_agency_portfolios() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("me/accounts"):
            assert "business{id,name}" in request.url.params["fields"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "p1",
                            "tasks": ["MANAGE"],
                            "business": {"id": "b1", "name": "Bir"},
                        },
                        {"id": "p2", "tasks": ["MANAGE"]},
                        {"id": "p3", "tasks": ["ADVERTISE"]},
                    ]
                },
            )
        if path.endswith("me/businesses"):
            return httpx.Response(200, json={"data": [{"id": "ag"}]})
        if path.endswith("ag/client_pages"):
            return httpx.Response(200, json={"data": [{"id": "p1"}, {"id": "p3"}]})
        raise AssertionError(path)

    pages = {p.id: p for p in list_pages(token="t", client=_graph(handler))}

    assert pages["p1"].business_ids == ("b1", "ag")
    assert pages["p1"].business_name == "Bir"
    assert pages["p2"].business_state == "personal"
    # Not an admin, but an agency holds it: known all the same.
    assert pages["p3"].business_state == "business"


def test_a_refused_business_field_leaves_the_page_unknown_not_personal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("me/accounts"):
            if "business{" in request.url.params["fields"]:
                return httpx.Response(
                    400, json={"error": {"code": 200, "message": "no"}}
                )
            return httpx.Response(
                200, json={"data": [{"id": "p1", "tasks": ["MANAGE"]}]}
            )
        return httpx.Response(200, json={"data": []})

    [page] = list_pages(token="t", client=_graph(handler))

    assert page.business_asked is False
    assert page.business_state == "unknown"


def test_an_account_lists_every_portfolio_it_was_reached_through() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("me/adaccounts"):
            return httpx.Response(
                200, json={"data": [{"id": "act_1", "business": {"id": "owner"}}]}
            )
        if path.endswith("me/businesses"):
            return httpx.Response(
                200, json={"data": [{"id": "owner"}, {"id": "client"}]}
            )
        if path.endswith("owner/owned_ad_accounts"):
            return httpx.Response(200, json={"data": [{"id": "act_1"}]})
        if path.endswith("client/client_ad_accounts"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "act_1", "business": {"id": "owner"}},
                        {"id": "act_2"},
                    ]
                },
            )
        return httpx.Response(200, json={"data": []})

    accounts = {a.id: a for a in list_ad_accounts(token="t", client=_graph(handler))}

    assert accounts["act_1"].business_ids == ("owner", "client")
    assert accounts["act_2"].business_ids == ("client",)
