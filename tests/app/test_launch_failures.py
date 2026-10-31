"""A refused launch says what happened and what to press, never a guess at waiting."""

from typing import Any

import pytest

from app.modules.ads.contract.launch.failures import failure
from app.modules.ads.contract.launch.media import library
from app.modules.ads.services.creation import FAILURE_CODES
from core.chat.preparations import TROUBLE_WORDS

WAIT = "5–10 daqiqa"
TEMPORARY = {"temporary", "rate_limited", "stalled"}
# Not refusals of a creation: they stop the wizard before anything is sent.
NOT_CREATION = {"subscription_expired", "refused", "unknown"}


def _failed(code: str, **state: Any) -> dict[str, Any]:
    return failure(
        {"error_code": code, **state},
        ads_total=2,
        page="Sahifa",
        budget="10 000 so'm",
        minimum="15 000 so'm",
    )


CREATION_CODES = sorted(
    (set(FAILURE_CODES.values()) | set(TROUBLE_WORDS)) - NOT_CREATION
)


@pytest.mark.parametrize("code", CREATION_CODES)
def test_every_refusal_we_can_name_has_its_own_help(code: str) -> None:
    found = _failed(code)

    assert found["code"] != "other"
    assert found["guide"]["steps"]


@pytest.mark.parametrize(
    "code", [code for code in CREATION_CODES if code not in TEMPORARY]
)
def test_only_a_passing_fault_is_told_to_wait(code: str) -> None:
    found = _failed(code)

    assert WAIT not in " ".join(found["guide"]["steps"])
    assert "keyin qayta" not in found["hint"]


@pytest.mark.parametrize("code", sorted(TEMPORARY))
def test_a_passing_fault_is_told_to_wait(code: str) -> None:
    assert WAIT in " ".join(_failed(code)["guide"]["steps"])


def test_the_billing_address_is_this_accounts_own() -> None:
    found = _failed("payment_missing", billing_url="https://billing/act_1")

    assert found["code"] == "payment"
    assert found["fix"]["href"] == "https://billing/act_1"


def test_the_terms_address_is_this_pages_own() -> None:
    found = _failed("page_terms", page_terms_url="https://terms/9")

    assert found["fix"]["href"] == "https://terms/9"


def test_a_refusal_with_no_name_is_not_told_to_wait() -> None:
    found = _failed("refused", error_message="Invalid parameter | code 100/1487")

    assert found["code"] == "other"
    assert WAIT not in " ".join(found["guide"]["steps"])
    assert "keyin" not in found["hint"]


@pytest.mark.parametrize("code", ["refused", "unknown", "payment_missing"])
def test_the_log_line_never_reaches_the_owner(code: str) -> None:
    line = "Invalid parameter | blamed: daily_budget | code 100/1487"

    found = _failed(code, error_message=line)

    assert "Invalid parameter" not in str(found)
    assert "code 100" not in str(found)


def test_what_meta_wrote_for_the_advertiser_is_shown() -> None:
    found = _failed(
        "refused",
        error_message="Invalid parameter | code 100/1487",
        error_detail={"title": "Byudjet kam", "message": "Kamida 1$ kiriting."},
    )

    assert found["raw"] == "Byudjet kam — Kamida 1$ kiriting."
    assert "Kamida 1$ kiriting." in found["guide"]["cause"]


def test_a_refused_file_carries_its_refusal_to_the_grid() -> None:
    refusal = {"title": "Meta faylni qabul qilmadi", "cause": "x", "key": "media:meta:1"}
    page = {
        "tiles": [
            {
                "asset": {"id": "a1", "name": "rasm.jpg", "kind": "image"},
                "delete_failed": True,
                "delete_refusal": refusal,
            }
        ],
        "variants": [
            {
                "position": 0,
                "is_upload": True,
                "upload_name": "video.mp4",
                "upload_failed": True,
                "upload_refusal": refusal,
            }
        ],
    }

    grid = library(None, page)

    assert grid["library"][0]["state"] == "delete_failed"
    assert grid["library"][0]["refusal"] == refusal
    assert [tile["refusal"] for tile in grid["uploads"]] == [refusal]
