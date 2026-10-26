"""An ad account's money, read on every sync and translated once."""

from typing import Any

import pytest
from adskit.refs import ExternalRef
from metaads.account_state import read_account_state, standing_of
from metaads.errors import MetaAPIError

ACCOUNT = ExternalRef(provider="meta", level="account", id="act_1")


@pytest.mark.parametrize(
    ("status", "reason", "standing"),
    [
        (1, 0, "active"),
        (3, 0, "payment_failed"),
        (8, 0, "payment_pending"),
        (9, 0, "payment_grace"),
        (2, 3, "disabled_payment"),
        (2, 1, "disabled"),
        (101, 0, "closed"),
        (0, 0, "unknown"),
    ],
)
def test_the_two_numbers_become_one_word(
    status: int, reason: int, standing: str
) -> None:
    assert standing_of(status=status, reason=reason) == standing


class Graph:
    """Answers the full read, or refuses it once when ``refuse`` is set."""

    def __init__(self, payload: dict[str, Any], *, refuse: bool = False) -> None:
        self.payload = payload
        self.refuse = refuse
        self.asked: list[str] = []

    def get(self, path: str, *, fields: str) -> dict[str, Any]:
        self.asked.append(fields)
        if self.refuse and "is_prepay_account" in fields:
            raise MetaAPIError("no role", code=200)
        return self.payload


def test_money_arrives_in_minor_units_whatever_its_shape() -> None:
    graph = Graph(
        {
            "account_status": 3,
            "spend_cap": "5000",
            "amount_spent": 5000,
            "balance": "1200",
            "is_prepay_account": True,
        }
    )

    state = read_account_state(account=ACCOUNT, token="t", client=graph)  # type: ignore[arg-type]

    assert state.standing == "payment_failed"
    assert state.cap_reached
    assert state.balance_minor == 1200
    assert state.prepaid is True


def test_a_token_without_the_role_still_gets_the_money_half() -> None:
    graph = Graph({"account_status": 1}, refuse=True)

    state = read_account_state(account=ACCOUNT, token="t", client=graph)  # type: ignore[arg-type]

    assert len(graph.asked) == 2
    assert state.standing == "active"
    assert state.prepaid is None
