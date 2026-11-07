"""Every creative turns down Meta's own changes to it.

What is pinned: both blocks travel on all three routes that make a
creative, a refusal is answered by sending less, the last refusal is the
one the creative would have had without the blocks, and the read-back
names what Meta kept switched on.
"""

import json
import logging
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from metaads.boosts import BoostSpec, create_boost_creative
from metaads.enhancements import (
    FEATURES,
    FEATURES_KEY,
    MUSIC_KEY,
    opted_out,
    still_on,
)
from metaads.errors import MetaAPIError
from metaads.restage import create_from_story
from metaads.specs import CreativeSpec
from metaads.stories import create_creative

CREATIVE = CreativeSpec(
    name="c",
    page_id="99",
    message="Salom",
    image_hash="abc",
    link_url="https://targetolog.ai/",
)


def answering(
    monkeypatch: pytest.MonkeyPatch,
    *,
    refusals: int = 0,
    read: dict[str, Any] | None = None,
) -> list[httpx.Request]:
    """Refuse the first ``refusals`` posts, then make the creative."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=read or {})
        posts = sum(1 for each in seen if each.method == "POST")
        if posts <= refusals:
            return httpx.Response(
                400,
                json={"error": {"code": 100, "message": f"Invalid parameter {posts}"}},
            )
        return httpx.Response(200, json={"id": "777"})

    original = httpx.Client.__init__

    def patched(self: httpx.Client, **kwargs: Any) -> None:
        original(self, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched)
    monkeypatch.setattr("metaads.client._shared", None)
    return seen


def posted(request: httpx.Request) -> dict[str, Any]:
    form = parse_qs(request.content.decode())
    return {key: values[0] for key, values in form.items()}


def blocks(request: httpx.Request) -> set[str]:
    return set(posted(request)) & {FEATURES_KEY, MUSIC_KEY}


# --- What travels ---------------------------------------------------------
def test_every_feature_is_turned_down() -> None:
    spec = opted_out()[FEATURES_KEY]["creative_features_spec"]

    assert set(spec) == set(FEATURES)
    assert {value["enroll_status"] for value in spec.values()} == {"OPT_OUT"}


def test_music_goes_out_as_an_empty_list_of_audios() -> None:
    """The guide's words: pass ``audios`` in as empty."""
    assert opted_out()[MUSIC_KEY] == {"audios": []}


def test_no_deprecated_feature_is_sent() -> None:
    """``standard_enhancements`` stopped applying in v22.0."""
    assert "standard_enhancements" not in FEATURES


@pytest.mark.parametrize("route", ["story", "boost", "restage"])
def test_all_three_routes_send_both_blocks(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    seen = answering(monkeypatch)

    if route == "story":
        create_creative(account_id="act_1", spec=CREATIVE, token="t", dry_run=False)
    elif route == "boost":
        create_boost_creative(
            account_id="act_1",
            spec=BoostSpec(page_id="99", instagram_user_id="77", media_id="17999"),
            token="t",
            dry_run=False,
        )
    else:
        create_from_story(
            account_id="act_1",
            name="c",
            story={"page_id": "99", "link_data": {"message": "Salom"}},
            token="t",
            dry_run=False,
        )

    first = posted(seen[0])
    assert blocks(seen[0]) == {FEATURES_KEY, MUSIC_KEY}
    features = json.loads(first[FEATURES_KEY])["creative_features_spec"]
    assert features["image_touchups"] == {"enroll_status": "OPT_OUT"}
    assert json.loads(first[MUSIC_KEY]) == {"audios": []}


def test_a_rehearsal_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = answering(monkeypatch)

    create_creative(account_id="act_1", spec=CREATIVE, token="t", dry_run=True)

    assert seen == []


# --- A refusal ------------------------------------------------------------
def test_a_refusal_is_answered_without_the_music_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = answering(monkeypatch, refusals=1)

    made = create_creative(account_id="act_1", spec=CREATIVE, token="t", dry_run=False)

    posts = [each for each in seen if each.method == "POST"]
    assert made == "777"
    assert [blocks(each) for each in posts] == [
        {FEATURES_KEY, MUSIC_KEY},
        {FEATURES_KEY},
    ]


def test_then_without_either(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = answering(monkeypatch, refusals=2)

    made = create_creative(account_id="act_1", spec=CREATIVE, token="t", dry_run=False)

    posts = [each for each in seen if each.method == "POST"]
    assert made == "777"
    assert blocks(posts[-1]) == set()
    assert posted(posts[-1])["name"] == "c"


def test_the_last_refusal_is_the_one_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three refusals: the third was the creative with neither block - the
    request this product sent before them - and its refusal is the answer."""
    seen = answering(monkeypatch, refusals=3)

    with pytest.raises(MetaAPIError, match="Invalid parameter 3"):
        create_creative(account_id="act_1", spec=CREATIVE, token="t", dry_run=False)

    assert len([each for each in seen if each.method == "POST"]) == 3


def test_a_creative_made_with_less_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    answering(monkeypatch, refusals=1)

    with caplog.at_level(logging.WARNING, logger="metaads.enhancements"):
        create_creative(account_id="act_1", spec=CREATIVE, token="t", dry_run=False)

    assert "made without ['asset_feed_spec']" in caplog.text


# --- The read-back --------------------------------------------------------
def test_the_new_creative_is_read_back(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = answering(monkeypatch)

    create_creative(account_id="act_1", spec=CREATIVE, token="t", dry_run=False)

    reads = [each for each in seen if each.method == "GET"]
    assert len(reads) == 1
    assert "777" in reads[0].url.path
    assert FEATURES_KEY in reads[0].url.params["fields"]


def test_a_feature_meta_kept_on_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    answering(
        monkeypatch,
        read={
            FEATURES_KEY: {
                "creative_features_spec": {
                    "image_touchups": {"enroll_status": "OPT_IN"},
                    "text_optimizations": {"enroll_status": "OPT_OUT"},
                }
            }
        },
    )

    with caplog.at_level(logging.WARNING, logger="metaads.enhancements"):
        create_creative(account_id="act_1", spec=CREATIVE, token="t", dry_run=False)

    assert "still holds Meta changes: ['image_touchups']" in caplog.text


def test_only_an_explicit_opt_in_counts() -> None:
    row = {
        FEATURES_KEY: {
            "creative_features_spec": {
                "standard_enhancements": {"enroll_status": "OPT_IN"},
                "image_uncrop": {"enroll_status": "OPT_OUT"},
                "video_auto_crop": {},
            }
        }
    }

    assert still_on(row) == ["standard_enhancements"]
    assert still_on({}) == []
