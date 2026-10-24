"""Reading an Instagram account's profile - the card a person recognises.

Nothing here reaches a network. What is under test is which node is asked,
which fields ride on the question, and what the parser makes of an answer
that leaves things out - which Meta does per account and without notice.
"""

import httpx
import pytest
from metaads.errors import MetaAPIError
from metaads.instagram import (
    IG_PROFILE_FIELDS,
    read_instagram_account,
    read_instagram_profile,
)
from metaads.instagram_rows import InstagramProfileDTO
from metaads.oauth import authorize_url

from tests.packages.test_metaads_client import client_returning

PROFILE = {
    "id": "17841400000000001",
    "username": "zuho.uz",
    "name": "Zuho Tailoring",
    "biography": "Erkaklar kostyumi · Toshkent",
    "website": "https://zuho.uz",
    "profile_picture_url": "https://scontent.cdninstagram.com/v/p.jpg?_nc_sig=x",
    "followers_count": 1240,
    "follows_count": 80,
    "media_count": 112,
}


def test_the_profile_is_asked_of_the_instagram_node_itself() -> None:
    """Not ``/{page-id}``: the page is how the account was found, and a
    page answers with its own name and picture, which are not these."""
    captured: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json=PROFILE), capture=captured)

    read_instagram_profile(ig_user_id="ig-1", token="t", client=graph)

    assert captured[0].url.path.endswith("/ig-1")


@pytest.mark.parametrize(
    "field",
    [
        "username",
        "name",
        "biography",
        "followers_count",
        "follows_count",
        "media_count",
    ],
)
def test_every_field_the_card_draws_is_asked_for(field: str) -> None:
    """A field left off the question is a blank on the card, and nothing
    about a blank says it was never asked."""
    assert field in IG_PROFILE_FIELDS.split(",")


def test_a_full_answer_arrives_whole() -> None:
    graph = client_returning(httpx.Response(200, json=PROFILE))

    profile = read_instagram_profile(ig_user_id="ig-1", token="t", client=graph)

    assert profile == InstagramProfileDTO(**PROFILE)
    assert profile.followers_count == 1240


def test_a_count_meta_left_out_is_unknown_and_not_nought() -> None:
    """ "0 followers" printed for an answer that simply omitted the count
    would tell somebody something false about their own business."""
    graph = client_returning(
        httpx.Response(200, json={"id": "ig-1", "username": "zuho.uz"})
    )

    profile = read_instagram_profile(ig_user_id="ig-1", token="t", client=graph)

    assert profile.followers_count is None
    assert profile.media_count is None
    assert profile.biography == ""


def test_text_that_is_not_text_reads_as_none_rather_than_failing() -> None:
    """A profile name that is only digits is a name somebody typed, and it
    must not cost the whole read its type."""
    profile = InstagramProfileDTO.model_validate(
        {"id": "ig-1", "name": 2026, "biography": None, "followers_count": "15"}
    )

    assert profile.name == ""
    assert profile.biography == ""
    assert profile.followers_count == 15


def test_a_count_that_is_not_a_number_is_unknown() -> None:
    profile = InstagramProfileDTO.model_validate(
        {"id": "ig-1", "followers_count": "many", "follows_count": True}
    )

    assert profile.followers_count is None
    assert profile.follows_count is None


def test_an_answer_without_an_id_is_the_package_s_own_failure() -> None:
    """The one field that is not optional. Without it the answer is not
    about any account, and the caller catches ``MetaError`` - pydantic's
    own error would reach it as a traceback."""
    graph = client_returning(httpx.Response(200, json={"username": "zuho.uz"}))

    with pytest.raises(MetaAPIError):
        read_instagram_profile(ig_user_id="ig-1", token="t", client=graph)


def test_the_console_can_ask_for_fewer_fields() -> None:
    """How a ``#100`` over one field name is bisected."""
    captured: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json=PROFILE), capture=captured)

    read_instagram_account(
        ig_user_id="ig-1", token="t", fields="id,username", client=graph
    )

    assert captured[0].url.params["fields"] == "id,username"


def test_the_dialog_asks_again_for_what_was_declined() -> None:
    """Without it, Meta's dialog skips a permission somebody unticked once,
    and "Qayta ulash" returns the very token it was meant to widen."""
    url = authorize_url(app_id="1", redirect_uri="https://e.com/", state="s")

    assert "auth_type=rerequest" in url
