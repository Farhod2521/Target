"""A launch on an account the connected login cannot reach stops before anything
is sent, and the account is marked - not swallowed with every other failed read."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from adskit.dto import AccountStateDTO
from adskit.errors import AdAccountUnreachable, TemporaryFailure
from adskit.refs import ExternalRef, ProviderName

from app.modules.ads.exceptions import AdAccountOutOfReach
from app.modules.ads.services import access, preflight
from app.modules.ads.services.creation import FAILURE_CODES
from app.modules.ads.services.manage import PROVIDER_FAILURES
from app.modules.integrations.services import reach

REF = ExternalRef(provider=ProviderName("meta"), level="account", id="act_1")
STATE = AccountStateDTO(ref=REF, standing="active", raw_status="1")
LOST = datetime(2026, 11, 9, tzinfo=UTC)


def _account(**fields: object) -> SimpleNamespace:
    return SimpleNamespace(
        provider="meta",
        external_id="act_1",
        connection_id="c1",
        reach_lost_at=None,
        **fields,
    )


def _meta_answers(monkeypatch: pytest.MonkeyPatch, answer: object) -> None:
    def read_account(*, account: ExternalRef, token: str) -> AccountStateDTO:
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[return-value]

    bundle = SimpleNamespace(campaigns=SimpleNamespace(read_account=read_account))
    monkeypatch.setattr(reach.registry, "get", lambda provider: bundle)
    monkeypatch.setattr(access, "token_for", lambda ad_account: "token")


def test_an_unreachable_account_stops_the_launch_and_is_marked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _meta_answers(monkeypatch, AdAccountUnreachable("owner has not grant", code="200"))
    account = _account()
    db = MagicMock()

    with pytest.raises(AdAccountOutOfReach):
        preflight._read_state(db, account=account)  # type: ignore[arg-type]

    assert account.reach_lost_at is not None
    db.commit.assert_called_once()


def test_a_reachable_account_is_read_and_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _meta_answers(monkeypatch, STATE)
    account = _account()
    account.reach_lost_at = LOST

    assert preflight._read_state(MagicMock(), account=account) is STATE  # type: ignore[arg-type]
    assert account.reach_lost_at is None


def test_any_other_failed_read_carries_on_unmarked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _meta_answers(monkeypatch, TemporaryFailure("later"))
    account = _account()

    assert preflight._read_state(MagicMock(), account=account) is None  # type: ignore[arg-type]
    assert account.reach_lost_at is None


def test_a_mark_already_made_keeps_its_time() -> None:
    account = _account()
    account.reach_lost_at = LOST

    reach.lose_reach(account)  # type: ignore[arg-type]

    assert account.reach_lost_at == LOST


def test_a_refused_write_reads_as_account_access() -> None:
    assert FAILURE_CODES["AdAccountUnreachable"] == "account_access"
    assert PROVIDER_FAILURES["AdAccountUnreachable"] == "account_access"
