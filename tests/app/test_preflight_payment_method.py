"""A launch on an account without a card stops before anything is made."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from adskit.dto import AccountStateDTO
from adskit.refs import ExternalRef, ProviderName

from app.modules.ads.exceptions import AdAccountNoPaymentMethod
from app.modules.ads.services import preflight

REF = ExternalRef(provider=ProviderName("meta"), level="account", id="act_1")


def _account() -> SimpleNamespace:
    return SimpleNamespace(external_id="act_1", prepaid=None, account_status="1")


def _read(monkeypatch: pytest.MonkeyPatch, **state: object) -> None:
    dto = AccountStateDTO(ref=REF, standing="active", raw_status="1", **state)
    monkeypatch.setattr(preflight, "_read_state", lambda db, account: dto)


def test_no_payment_method_stops_the_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    _read(monkeypatch, has_payment_method=False)

    with pytest.raises(AdAccountNoPaymentMethod):
        preflight._check_payment_method(MagicMock(), account=_account())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "state",
    [
        {"has_payment_method": True},
        {"has_payment_method": None},
        {"has_payment_method": False, "prepaid": True},
    ],
)
def test_a_card_an_unread_field_or_a_prepaid_account_carries_on(
    monkeypatch: pytest.MonkeyPatch, state: dict[str, object]
) -> None:
    _read(monkeypatch, **state)

    preflight._check_payment_method(MagicMock(), account=_account())  # type: ignore[arg-type]


def test_an_unreadable_account_carries_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "_read_state", lambda db, account: None)

    preflight._check_payment_method(MagicMock(), account=_account())  # type: ignore[arg-type]
