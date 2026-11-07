"""TZ 2: what ``POST /{id}/copies`` is sent, and what is read back."""

import json
from typing import Any
from urllib.parse import parse_qs

import httpx
from metaads.client import GraphClient
from metaads.copies import copy_ad, copy_adset, copy_campaign


def answering(payload: dict[str, Any]) -> tuple[GraphClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    ), seen


def _form(request: httpx.Request) -> dict[str, str]:
    return {
        key: values[0] for key, values in parse_qs(request.content.decode()).items()
    }


def test_a_campaign_alone_is_copied_paused_and_only_it_renamed() -> None:
    client, seen = answering({"copied_campaign_id": "9"})

    made = copy_campaign(
        campaign_id="1", suffix=" — nusxa", token="t", client=client, dry_run=False
    )

    sent = _form(seen[0])
    assert made == "9" and seen[0].url.path.endswith("/1/copies")
    assert (sent["deep_copy"], sent["status_option"]) == ("false", "PAUSED")
    assert json.loads(sent["rename_options"]) == {
        "rename_strategy": "ONLY_TOP_LEVEL_RENAME",
        "rename_suffix": " — nusxa",
    }


def test_a_group_goes_into_the_campaign_named_with_its_adverts() -> None:
    client, seen = answering({"copied_adset_id": "8"})

    made = copy_adset(
        adset_id="2",
        campaign_id="9",
        deep_copy=True,
        status="INHERITED_FROM_SOURCE",
        token="t",
        client=client,
        dry_run=False,
    )

    sent = _form(seen[0])
    assert made == "8"
    assert (sent["campaign_id"], sent["deep_copy"]) == ("9", "true")
    assert json.loads(sent["rename_options"]) == {"rename_strategy": "NO_RENAME"}


def test_an_advert_keeps_its_creative_unless_one_is_given() -> None:
    client, seen = answering({"copied_ad_id": "7"})

    copy_ad(
        ad_id="3",
        adset_id="8",
        status="ACTIVE",
        token="t",
        client=client,
        dry_run=False,
    )

    sent = _form(seen[0])
    assert "creative_parameters" not in sent
    assert (sent["adset_id"], sent["status_option"]) == ("8", "ACTIVE")


def test_a_dry_run_reaches_nothing() -> None:
    client, seen = answering({})

    assert copy_ad(ad_id="3", status="PAUSED", token="t", client=client).startswith(
        "dry"
    )
    assert seen == []
