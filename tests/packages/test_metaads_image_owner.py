"""Whose picture a library row is, and why that decides whether an ad shows it.

``/act_<id>/adimages`` lists pictures other accounts own beside the
account's own. A creative built on one of those is accepted, its ad is
accepted, and delivery fails with "Image Not Found". The rows below are the
two shapes a live account answered with.
"""

from typing import Any

import httpx
from metaads.client import GraphClient
from metaads.creatives import (
    belongs_to,
    describe_image,
    list_media,
    own_image_hashes,
)
from metaads.discovery import IMAGE_FIELDS

OWN = {"hash": "aaa", "name": "menu.png", "id": "973723461793046:aaa"}
FOREIGN = {
    "hash": "bbb",
    "name": "Screenshot.png",
    "id": "120249046100170521:bbb",
    "account_id": "120249046100170521",
}


def by_path(
    answers: dict[str, dict[str, Any]],
) -> tuple[GraphClient, list[httpx.Request]]:
    """One mock transport answering by the last part of the path."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        edge = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=answers.get(edge, {"data": []}))

    client = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client, seen


# --- One row ---------------------------------------------------------------
def test_the_accounts_own_row_belongs_to_it() -> None:
    assert belongs_to(OWN, account_id="act_973723461793046")


def test_a_row_owned_elsewhere_does_not() -> None:
    assert not belongs_to(FOREIGN, account_id="act_973723461793046")


def test_the_owner_is_read_from_account_id_when_the_id_has_none() -> None:
    row = {"hash": "bbb", "account_id": "120249046100170521"}

    assert not belongs_to(row, account_id="act_973723461793046")
    assert belongs_to(row, account_id="act_120249046100170521")


def test_a_row_that_names_no_owner_is_kept() -> None:
    """Silence is not a verdict - it would empty a library over one field."""
    assert belongs_to({"hash": "ccc"}, account_id="act_1")


def test_the_owner_is_asked_for() -> None:
    assert "account_id" in IMAGE_FIELDS.split(",")


# --- The library -----------------------------------------------------------
def test_the_library_leaves_out_pictures_another_account_owns() -> None:
    graph, _ = by_path({"adimages": {"data": [OWN, FOREIGN]}})

    media = list_media(account_id="act_973723461793046", token="t", client=graph)

    assert [item.external_id for item in media] == ["aaa"]


def test_videos_are_not_filtered() -> None:
    graph, _ = by_path(
        {
            "adimages": {"data": [FOREIGN]},
            "advideos": {"data": [{"id": "777", "title": "reel"}]},
        }
    )

    media = list_media(account_id="act_973723461793046", token="t", client=graph)

    assert [(item.kind, item.external_id) for item in media] == [("video", "777")]


def test_a_foreign_row_is_not_described_as_the_upload() -> None:
    graph, _ = by_path({"adimages": {"data": [FOREIGN]}})

    media = describe_image(
        account_id="act_973723461793046", image_hash="bbb", token="t", client=graph
    )

    assert media.external_id == "bbb"
    assert media.name == ""


# --- Before a creative -----------------------------------------------------
def test_only_the_accounts_own_hashes_come_back() -> None:
    graph, seen = by_path({"adimages": {"data": [OWN, FOREIGN]}})

    owned = own_image_hashes(
        account_id="act_973723461793046",
        hashes=["aaa", "bbb", "aaa"],
        token="t",
        client=graph,
    )

    assert owned == frozenset({"aaa"})
    assert seen[0].url.params["hashes"] == '["aaa", "bbb"]'


def test_a_hash_meta_does_not_list_is_not_owned() -> None:
    graph, _ = by_path({"adimages": {"data": []}})

    assert (
        own_image_hashes(
            account_id="act_973723461793046", hashes=["aaa"], token="t", client=graph
        )
        == frozenset()
    )


def test_no_hashes_ask_nothing() -> None:
    graph, seen = by_path({})

    assert own_image_hashes(
        account_id="act_1", hashes=[""], token="t", client=graph
    ) == (frozenset())
    assert seen == []
