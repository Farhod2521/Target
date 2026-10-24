"""Reading named objects by id, and what one broken advert must not cost.

The account lists are all or nothing: one advert Meta refuses to describe
fails ``/act_<id>/ads`` for every ad in the account. These pin the read that
replaced them for a launch - it asks for its own ids only, each at its own
path because Graph v26.0 refuses ``?ids=``, and still answers for an ad
whose Advantage+ creative Meta will not read back.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from adskit.refs import ExternalRef
from metaads.adapter import MetaCampaigns
from metaads.campaigns import list_ads
from metaads.client import GraphClient
from metaads.errors import MetaAPIError
from metaads.objects import (
    AD_FIELDS_WITHOUT_CONTENT,
    UNREADABLE_CREATIVE_SUBCODE,
    read_ads,
    read_campaigns,
)

CAMPAIGN = {"id": "120210", "name": "Lidlar", "status": "PAUSED"}
AD = {
    "id": "3401",
    "name": "Video",
    "adset_id": "2301",
    "status": "PAUSED",
    "effective_status": "PAUSED",
    "creative": {"id": "555", "object_story_spec": {"page_id": "99"}},
}

DOF_REFUSAL = {
    "error": {
        "message": "Invalid parameter",
        "type": "OAuthException",
        "code": 100,
        "error_subcode": UNREADABLE_CREATIVE_SUBCODE,
        "error_user_title": "First Dof Value Should Match Object Story Spec Field",
    }
}


def graph(handler) -> GraphClient:
    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def query(request: httpx.Request) -> dict[str, str]:
    return {
        key: values[0]
        for key, values in parse_qs(urlparse(str(request.url)).query).items()
    }


def path_id(request: httpx.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1]


IDS_DEPRECATED = {
    "error": {
        "message": "The ids query parameter is deprecated in v26.0+.",
        "type": "OAuthException",
        "code": 100,
    }
}


def test_each_id_is_read_at_its_own_path_and_nothing_else() -> None:
    """One request per id - never the account's list, never ``?ids=``,
    which v26.0 refuses for every launch."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "ids" in query(request):
            return httpx.Response(400, json=IDS_DEPRECATED)
        return httpx.Response(200, json={**CAMPAIGN, "id": path_id(request)})

    rows = read_campaigns(ids=["120210", "120211"], token="t", client=graph(handler))

    assert [row.id for row in rows] == ["120210", "120211"]
    assert [path_id(request) for request in seen] == ["120210", "120211"]
    assert all("act_" not in request.url.path for request in seen)
    assert all("ids" not in query(request) for request in seen)


def test_a_repeated_or_empty_id_is_asked_for_once() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(path_id(request))
        return httpx.Response(200, json={**CAMPAIGN, "id": path_id(request)})

    read_campaigns(ids=["120210", "", "120210"], token="t", client=graph(handler))

    assert seen == ["120210"]


def test_an_ad_meta_will_not_describe_still_comes_back_without_its_content() -> None:
    """The refusal that kept a whole account out of the mirror. The ad's
    status is what switching it on needs, and that is still read."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fields = query(request)["fields"]
        asked.append(fields)
        if fields == AD_FIELDS_WITHOUT_CONTENT:
            return httpx.Response(200, json={**AD, "creative": {"id": "555"}})
        return httpx.Response(400, json=DOF_REFUSAL)

    rows = read_ads(ids=["3401"], token="t", client=graph(handler))

    assert [row.id for row in rows] == ["3401"]
    assert rows[0].status == "PAUSED"
    assert rows[0].creative_external_id == "555"
    assert asked[-1] == AD_FIELDS_WITHOUT_CONTENT


def test_one_ad_meta_will_not_describe_does_not_cost_the_others() -> None:
    """The others answer in full; the broken one without its content."""

    def handler(request: httpx.Request) -> httpx.Response:
        object_id = path_id(request)
        if object_id == "bad" and query(request)["fields"] != AD_FIELDS_WITHOUT_CONTENT:
            return httpx.Response(400, json=DOF_REFUSAL)
        return httpx.Response(200, json={**AD, "id": object_id})

    rows = read_ads(ids=["3401", "bad"], token="t", client=graph(handler))

    assert sorted(row.id for row in rows) == ["3401", "bad"]


def test_a_gone_object_is_left_out_rather_than_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "Unsupported get request", "code": 803}}
        )

    assert read_campaigns(ids=["120210"], token="t", client=graph(handler)) == []


def test_an_id_missing_at_its_path_is_left_out_and_the_rest_still_read() -> None:
    """Graph answers a deleted id at its own path with 100/33, not 803."""

    def handler(request: httpx.Request) -> httpx.Response:
        if path_id(request) == "deleted":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported get request.",
                        "code": 100,
                        "error_subcode": 33,
                    }
                },
            )
        return httpx.Response(200, json={**AD, "id": path_id(request)})

    rows = read_ads(ids=["deleted", "3401"], token="t", client=graph(handler))

    assert [row.id for row in rows] == ["3401"]


def test_a_refused_field_is_not_mistaken_for_a_gone_object() -> None:
    """A bare 100 is a refused value; dropping the row would hide it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "Invalid parameter", "code": 100}}
        )

    with pytest.raises(MetaAPIError):
        read_campaigns(ids=["120210"], token="t", client=graph(handler))


def test_the_port_answers_each_level_from_its_own_refs(monkeypatch) -> None:
    """Refs are sorted by level, and a level nobody asked for costs nothing."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        object_id = path_id(request)
        asked.append(object_id)
        return httpx.Response(200, json=CAMPAIGN if object_id == "120210" else AD)

    monkeypatch.setattr(
        "metaads.adapter.GraphClient",
        lambda token: graph(handler),
    )
    refs = [
        ExternalRef(provider="meta", level="campaign", id="120210"),
        ExternalRef(provider="meta", level="ad", id="3401"),
    ]

    found = MetaCampaigns().read_objects(
        account=ExternalRef(provider="meta", level="account", id="act_1"),
        refs=refs,
        token="t",
    )

    assert [c.ref.id for c in found.campaigns] == ["120210"]
    assert found.adsets == ()
    assert [a.ref.id for a in found.ads] == ["3401"]
    assert asked == ["120210", "3401"]


# --- The account list ------------------------------------------------------
def test_one_unreadable_creative_no_longer_empties_the_account_list() -> None:
    """The whole ``/ads`` edge used to fail for every ad in the account."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fields = query(request)["fields"]
        asked.append(fields)
        if fields != AD_FIELDS_WITHOUT_CONTENT:
            return httpx.Response(400, json=DOF_REFUSAL)
        return httpx.Response(
            200, json={"data": [{**AD, "creative": {"id": "555"}}], "paging": {}}
        )

    rows = list_ads(account_id="act_1", token="t", client=graph(handler))

    assert [row.id for row in rows] == ["3401"]
    assert rows[0].creative_external_id == "555"
    assert asked[-1] == AD_FIELDS_WITHOUT_CONTENT


def test_any_other_refusal_of_the_account_list_still_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "no", "type": "OAuthException", "code": 100}},
        )

    with pytest.raises(MetaAPIError):
        list_ads(account_id="act_1", token="t", client=graph(handler))
