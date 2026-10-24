"""A page can name two Instagram accounts, and both have to come through.

``instagram_business_account`` is the account linked while converting to
a professional one; ``connected_instagram_account`` is the one connected
in the page's settings afterwards. Reading only the first hid the second.
"""

import httpx
import pytest
from metaads.accounts import PAGE_FIELDS, list_pages
from metaads.client import GraphClient
from metaads.dto import PageDTO
from metaads.errors import MetaError


def test_both_fields_are_asked_for() -> None:
    assert "instagram_business_account{id,username}" in PAGE_FIELDS
    assert "connected_instagram_account{id,username}" in PAGE_FIELDS


def test_two_different_accounts_are_both_listed_business_one_first() -> None:
    page = PageDTO.model_validate(
        {
            "id": "1",
            "instagram_business_account": {"id": "a", "username": "shop"},
            "connected_instagram_account": {"id": "b", "username": "shop_kids"},
        }
    )

    assert [a.id for a in page.instagram_accounts] == ["a", "b"]
    assert page.instagram_id == "a"
    assert page.instagram_username == "shop"


def test_the_same_account_twice_is_listed_once() -> None:
    page = PageDTO.model_validate(
        {
            "id": "1",
            "instagram_business_account": {"id": "a", "username": "shop"},
            "connected_instagram_account": {"id": "a", "username": "shop"},
        }
    )

    assert [a.id for a in page.instagram_accounts] == ["a"]


def test_only_the_settings_connection_is_still_found() -> None:
    page = PageDTO.model_validate(
        {"id": "1", "connected_instagram_account": {"id": "b", "username": "x"}}
    )

    assert page.instagram_id == "b"


def test_a_page_with_neither_has_none() -> None:
    page = PageDTO.model_validate({"id": "1"})

    assert page.instagram_accounts == ()
    assert page.instagram_id == ""


def test_a_refused_second_field_costs_that_field_not_the_page_list() -> None:
    """``#100`` refuses the whole read over one field. The page list every
    screen stands on must survive it."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fields = request.url.params.get("fields", "")
        asked.append(fields)
        if "connected_instagram_account" in fields:
            return httpx.Response(
                400, json={"error": {"code": 100, "message": "Tried accessing"}}
            )
        return httpx.Response(200, json={"data": [{"id": "9", "name": "Osh"}]})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    pages = list_pages(token="t", client=graph)

    assert [page.id for page in pages] == ["9"]
    assert "connected_instagram_account" not in asked[-1]


def test_an_auth_refusal_is_not_hidden_by_the_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 190, "message": "expired"}})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(MetaError):
        list_pages(token="t", client=graph)
