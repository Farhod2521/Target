"""The night's read is asked again when Meta refused it for a reason that passes.

Until 2026-11-12 only a passing fault was retried, and once. An account
refused for the call budget - which the shared gate now does on purpose -
waited for the next night, with yesterday left as the day's last half-hourly
read had it.
"""

from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.ads.exceptions import SyncFailed
from app.modules.integrations.constants import ConnectionStatus
from app.modules.metrics import tasks
from app.modules.metrics.services.sync import InsightSummary, LevelSummary
from tests.pg.test_sweep_accounts import _account


@pytest.fixture
def queued(db: Session, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def apply_async(args: Any = None, kwargs: Any = None, **options: Any) -> None:
        sent.append({"args": args, "kwargs": kwargs, **options})

    @contextmanager
    def session() -> Any:
        yield db

    monkeypatch.setattr(tasks.sync_insights_task, "apply_async", apply_async)
    monkeypatch.setattr(tasks, "task_session", session)
    monkeypatch.setattr(settings, "metrics_retry_minutes", 12)
    return sent


def _fails(monkeypatch: pytest.MonkeyPatch, cause: str) -> None:
    def refuse(*_: Any, **__: Any) -> Any:
        raise SyncFailed(cause=cause)

    monkeypatch.setattr(tasks, "sync_insights", refuse)


@pytest.mark.parametrize("cause", ["rate_limited", "temporary", "provider_error"])
def test_a_refusal_that_passes_is_asked_again(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    queued: list[dict[str, Any]],
    cause: str,
) -> None:
    account = _account(db, 80, status=ConnectionStatus.ACTIVE)
    _fails(monkeypatch, cause)

    word = tasks.sync_insights_task(str(account.id))

    assert word.startswith(f"provider_failed:{cause} again_in:")
    assert queued[0]["args"] == [str(account.id)]
    assert queued[0]["kwargs"] == {"attempt": 1}
    assert 12 * 60 <= queued[0]["countdown"] < 12 * 60 + 180


def test_each_wait_is_longer_and_the_fourth_refusal_is_the_last(
    db: Session, monkeypatch: pytest.MonkeyPatch, queued: list[dict[str, Any]]
) -> None:
    account = _account(db, 81, status=ConnectionStatus.ACTIVE)
    _fails(monkeypatch, "rate_limited")

    words = [tasks.sync_insights_task(str(account.id), attempt=n) for n in range(4)]

    assert [row["kwargs"]["attempt"] for row in queued] == [1, 2, 3]
    waits = [row["countdown"] for row in queued]
    assert waits == sorted(waits) and waits[2] >= 36 * 60
    assert words[3] == "provider_failed:rate_limited"


def test_a_read_cut_short_at_the_same_page_is_not_asked_again(
    db: Session, monkeypatch: pytest.MonkeyPatch, queued: list[dict[str, Any]]
) -> None:
    account = _account(db, 82, status=ConnectionStatus.ACTIVE)
    _fails(monkeypatch, "truncated")

    assert tasks.sync_insights_task(str(account.id)) == "provider_failed:truncated"
    assert queued == []


def test_a_read_stopped_half_way_for_the_budget_is_finished_later(
    db: Session, monkeypatch: pytest.MonkeyPatch, queued: list[dict[str, Any]]
) -> None:
    from datetime import date

    account = _account(db, 83, status=ConnectionStatus.ACTIVE)
    day = date(2026, 11, 11)
    half = InsightSummary(
        levels=(LevelSummary(level="adset", rows=3, since=day, until=day),),
        stopped_at="campaign",
        stopped_by="rate_limited",
    )
    monkeypatch.setattr(tasks, "sync_insights", lambda *_, **__: half)

    word = tasks.sync_insights_task(str(account.id))

    assert "stopped:campaign by:rate_limited again_in:" in word
    assert len(queued) == 1
