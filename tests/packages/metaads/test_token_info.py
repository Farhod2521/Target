"""What ``debug_token`` says when it says a token is no good.

No network: this is a shape, and the shape is the point. Meta nests the
reason inside an ``error`` object, and ``extra="ignore"`` would drop it
without a word - which is how "expired" and "the person removed this app"
arrive as the same ``is_valid: false`` and get shown the same wrong
sentence.
"""

from datetime import UTC, datetime

from metaads.dto import TokenInfoDTO


def test_the_reason_is_lifted_out_of_the_nested_object() -> None:
    info = TokenInfoDTO.model_validate(
        {"is_valid": False, "error": {"code": 190, "subcode": 463}}
    )

    assert info.error_code == 190
    assert info.error_subcode == 463


def test_a_healthy_token_carries_no_reason() -> None:
    info = TokenInfoDTO.model_validate(
        {"is_valid": True, "scopes": ["ads_read"], "expires_at": 1790000000}
    )

    assert info.error_code == 0
    assert info.error_subcode == 0
    assert info.expires_at == datetime.fromtimestamp(1790000000, UTC)


def test_an_error_without_a_subcode_still_reads() -> None:
    info = TokenInfoDTO.model_validate({"is_valid": False, "error": {"code": 190}})

    assert info.error_code == 190
    assert info.error_subcode == 0


def test_an_error_of_the_wrong_shape_is_survived() -> None:
    """Somebody else's bug is not ours to raise on."""
    info = TokenInfoDTO.model_validate({"is_valid": False, "error": "boom"})

    assert info.error_code == 0


def test_zero_still_means_a_token_that_does_not_expire() -> None:
    """Meta's own way of saying "no deadline", and not "already dead"."""
    info = TokenInfoDTO.model_validate({"is_valid": True, "expires_at": 0})

    assert info.expires_at is None


def test_granular_scopes_name_the_assets_a_grant_covers() -> None:
    info = TokenInfoDTO.model_validate(
        {
            "is_valid": True,
            "scopes": ["instagram_basic", "ads_read"],
            "granular_scopes": [
                {"scope": "instagram_basic", "target_ids": ["17841", "17842"]},
                {"scope": "ads_read"},
            ],
        }
    )

    assert info.targets("instagram_basic") == ("17841", "17842")
    assert info.targets("ads_read") == ()
    assert info.targets("pages_show_list") == ()
