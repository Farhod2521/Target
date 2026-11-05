"""Reading the ninety days again: who is asked, and how far apart."""

from types import SimpleNamespace
from unittest.mock import patch

from app.modules.metrics import refill


def test_every_account_is_its_own_task_spaced_apart() -> None:
    found = [SimpleNamespace(id=f"a{n}") for n in range(3)]

    with patch("app.modules.metrics.tasks.refill_history_task.apply_async") as sent:
        assert refill.queue(found) == 3  # type: ignore[arg-type]

    assert [call.kwargs["countdown"] for call in sent.call_args_list] == [
        0,
        refill.SPACING_SECONDS,
        2 * refill.SPACING_SECONDS,
    ]
    assert [call.kwargs["args"] for call in sent.call_args_list] == [
        ["a0"],
        ["a1"],
        ["a2"],
    ]


def test_only_meta_accounts_are_read_again() -> None:
    swept = [
        SimpleNamespace(id="m", provider="meta"),
        SimpleNamespace(id="g", provider="google"),
    ]

    with patch("app.modules.ads.selectors.nightly_swept_accounts", return_value=swept):
        assert [one.id for one in refill.accounts(None)] == ["m"]  # type: ignore[arg-type]
