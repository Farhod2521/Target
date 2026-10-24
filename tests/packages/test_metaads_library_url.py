"""The address somebody is sent to when the file will not fit our tile.

Meta publishes no URL for an ad account's media library - its help pages
describe the menu path and stop there - so the address this builds was
transcribed from a browser that was sitting on it, and these tests are what
hold the transcription still. A link handed to a customer that lands on an
error is the failure mode the whole thing is arranged to avoid, which is
also why the no-business case is checked: it must fall back rather than
guess a scope.
"""

from metaads.account_rows import AdAccountDTO
from metaads.accounts import ASSET_LIBRARY_URL, manager_url, media_library_url

# The owner's own account and portfolio, as their browser spells them.
ACCOUNT = "act_120249046100170521"
BUSINESS = "2048055829353606"


def test_both_ids_build_the_ad_accounts_own_library() -> None:
    url = media_library_url(ACCOUNT, business_id=BUSINESS)

    assert url.startswith(ASSET_LIBRARY_URL)
    assert f"business_id={BUSINESS}" in url
    # Business Manager carries the scope twice and the address it answers on
    # has both. Dropping the second is not known to work.
    assert f"global_scope_id={BUSINESS}" in url


def test_the_account_travels_without_metas_prefix() -> None:
    """``act_`` belongs to the Graph id, not to the console address."""
    url = media_library_url(ACCOUNT, business_id=BUSINESS)

    assert "ad_account=120249046100170521" in url
    assert "act_" not in url


def test_an_account_with_no_business_falls_back_to_ads_manager() -> None:
    """A personal ad account, or a token that may not read the field.

    There is no library address without a portfolio to scope it to, and a
    button that lands on an error is worse than one that lands somewhere
    true and a menu step away.
    """
    assert media_library_url(ACCOUNT, business_id="") == manager_url(ACCOUNT)


def test_a_business_with_no_account_is_not_an_address_either() -> None:
    assert media_library_url("", business_id=BUSINESS) == manager_url("")


def test_the_business_arrives_flattened() -> None:
    """Meta answers an object; callers want the id and nothing else."""
    account = AdAccountDTO.model_validate({"id": ACCOUNT, "business": {"id": BUSINESS}})

    assert account.business_id == BUSINESS


def test_an_account_meta_said_nothing_about_answers_empty() -> None:
    """Absent and null are one thing here, and neither may raise: the whole
    account list is parsed in one pass, and a personal account in it must
    not take the others down."""
    assert AdAccountDTO.model_validate({"id": ACCOUNT}).business_id == ""
    assert (
        AdAccountDTO.model_validate({"id": ACCOUNT, "business": None}).business_id == ""
    )
