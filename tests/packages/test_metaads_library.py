"""Taking a file back off the ad account's library, and asking first.

The delete is the owner's own - a button with a confirmation behind it -
and the question before it is whether any creative still shows the file.
Both live here because the question is only worth asking of the same edge
the delete writes to.
"""

from typing import Any

import httpx
import pytest
from metaads.client import GraphClient
from metaads.creatives import describe_image, image_creatives
from metaads.errors import MetaAPIError
from metaads.uploads import delete_image, delete_video


def recording(
    payload: dict[str, Any],
) -> tuple[GraphClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    client = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client, seen


def exploding() -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"a dry run reached the network: {request.url}")

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


# --- Deleting --------------------------------------------------------------
def test_an_image_is_deleted_from_the_edge_it_was_uploaded_to() -> None:
    """By hash, because an image has no id and so no path of its own."""
    graph, seen = recording({"success": True})

    delete_image(
        account_id="act_1", image_hash="9f8e", token="t", client=graph, dry_run=False
    )

    assert seen[0].method == "DELETE"
    assert seen[0].url.path.endswith("/act_1/adimages")
    assert seen[0].url.params["hash"] == "9f8e"


def test_a_video_is_taken_off_the_accounts_edge() -> None:
    """Not ``DELETE /777``: the video belongs to its uploader, and Meta answers
    the account's token there with (#200) Permissions error."""
    graph, seen = recording({"success": True})

    delete_video(
        account_id="act_1", video_id="777", token="t", client=graph, dry_run=False
    )

    assert seen[0].method == "DELETE"
    assert seen[0].url.path.endswith("/act_1/advideos")
    assert seen[0].url.params["video_id"] == "777"


def test_a_delete_meta_did_not_confirm_is_refused() -> None:
    """Recorded as done, it would tell the owner a file is gone that is not."""
    graph, _ = recording({"success": False})

    with pytest.raises(MetaAPIError):
        delete_image(
            account_id="act_1",
            image_hash="9f8e",
            token="t",
            client=graph,
            dry_run=False,
        )


def test_a_yes_spelled_as_a_string_is_still_a_yes() -> None:
    graph, _ = recording({"success": "true"})

    delete_video(
        account_id="act_1", video_id="777", token="t", client=graph, dry_run=False
    )


def test_a_dry_run_delete_sends_nothing() -> None:
    graph = exploding()

    delete_image(account_id="act_1", image_hash="9f8e", token="t", client=graph)
    delete_video(account_id="act_1", video_id="777", token="t", client=graph)


# --- Reading one image back ------------------------------------------------
def test_an_uploaded_image_is_read_back_by_its_hash() -> None:
    """An upload answers with the hash alone; the grid needs a picture."""
    graph, seen = recording(
        {
            "data": [
                {
                    "hash": "9f8e",
                    "name": "menu.jpg",
                    "url": "https://x/menu.jpg",
                    "width": 1080,
                    "height": 1350,
                }
            ]
        }
    )

    media = describe_image(
        account_id="act_1", image_hash="9f8e", token="t", client=graph
    )

    assert media.kind == "image"
    assert media.external_id == "9f8e"
    assert media.name == "menu.jpg"
    assert media.thumbnail_url == "https://x/menu.jpg"
    assert (media.width, media.height) == (1080, 1350)
    assert seen[0].url.params["hashes"] == '["9f8e"]'


def test_an_image_meta_does_not_list_is_still_its_hash() -> None:
    """The hash is all a creative needs; the next sync fills in the rest."""
    graph, _ = recording({"data": []})

    media = describe_image(
        account_id="act_1", image_hash="9f8e", token="t", client=graph
    )

    assert media.external_id == "9f8e"
    assert media.kind == "image"
    assert media.thumbnail_url == ""


# --- Where an image is used ------------------------------------------------
def test_the_creatives_showing_an_image_are_listed() -> None:
    graph, seen = recording({"data": [{"hash": "9f8e", "creatives": ["111", "222"]}]})

    assert image_creatives(
        account_id="act_1", image_hash="9f8e", token="t", client=graph
    ) == ("111", "222")
    assert "creatives" in seen[0].url.params["fields"]


def test_creatives_sent_as_objects_are_read_by_their_id() -> None:
    graph, _ = recording({"data": [{"hash": "9f8e", "creatives": [{"id": "111"}]}]})

    assert image_creatives(
        account_id="act_1", image_hash="9f8e", token="t", client=graph
    ) == ("111",)


def test_an_image_no_creative_shows_answers_empty() -> None:
    graph, _ = recording({"data": [{"hash": "9f8e"}]})

    assert (
        image_creatives(account_id="act_1", image_hash="9f8e", token="t", client=graph)
        == ()
    )


def test_a_row_for_another_hash_is_not_this_image() -> None:
    """An edge that ignored the filter would answer with the whole library,
    and the first image's creatives would be read as this one's."""
    graph, _ = recording({"data": [{"hash": "other", "creatives": ["111"]}]})

    assert (
        image_creatives(account_id="act_1", image_hash="9f8e", token="t", client=graph)
        == ()
    )
