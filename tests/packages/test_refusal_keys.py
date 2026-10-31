"""Every adapter names a refusal by what reads the same in any language."""

from adskit.errors import TemporaryFailure
from metaads.adapter import translate_error
from metaads.errors import MetaAPIError, MetaError, MetaTemporaryError


def _key(error: MetaError) -> str:
    return translate_error(error).key


def test_a_refusal_is_named_by_its_code_and_subcode() -> None:
    assert _key(MetaAPIError("x", code=100, subcode=1487851)) == "meta:100/1487851"


def test_a_code_alone_is_narrowed_by_the_field_meta_blamed() -> None:
    error = MetaAPIError("x", code=100, blamed="daily_budget")

    assert _key(error) == "meta:100:daily_budget"


def test_a_code_with_nothing_beside_it_is_named_by_the_code() -> None:
    assert _key(MetaAPIError("x", code=100)) == "meta:100"


def test_a_failure_with_no_code_has_no_name() -> None:
    assert _key(MetaError("the network went away")) == ""


def test_the_name_survives_on_a_passing_fault_too() -> None:
    translated = translate_error(MetaTemporaryError("x", code=2, subcode=7))

    assert isinstance(translated, TemporaryFailure) and translated.retryable
    assert translated.key == "meta:2/7"


def test_google_is_named_by_its_own_word() -> None:
    from googleadskit.errors import GoogleAdsAPIError
    from googleadskit.translate import translate_error as google

    error = GoogleAdsAPIError("x", status="INVALID_ARGUMENT", http_status=400)

    assert google(error).key == "google:INVALID_ARGUMENT"
