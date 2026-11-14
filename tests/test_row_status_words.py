"""An unpaid or unread campaign says so; it is not «Tekshiruvda»."""

from types import SimpleNamespace

from app.modules.ads.contract.words import RUNNING, status_of, status_word


def test_an_unpaid_campaign_is_not_in_review() -> None:
    assert status_of(SimpleNamespace(delivery="billing")) == "billing"
    assert status_of(SimpleNamespace(delivery="unknown")) == "unknown"
    assert status_of(SimpleNamespace(delivery="pending")) == "pending"


def test_they_stay_where_the_owner_looks_first() -> None:
    assert {"billing", "unknown"} <= RUNNING


def test_other_networks_keep_their_words() -> None:
    assert status_word("billing") == "pending"
