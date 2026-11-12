"""Google's work on queues of its own, so a slow Google never holds Meta up."""

import uuid

import pytest

from app.common import task_routes
from app.common.meta_gate import CacheGate, is_background
from app.common.task_routes import (
    FIGURES_QUEUE,
    GOOGLE_QUEUE,
    GOOGLE_SYNC_QUEUE,
    ROUTED,
    route_task,
)
from app.worker import celery_app

GOOGLE_ACCOUNT, META_ACCOUNT = str(uuid.uuid4()), str(uuid.uuid4())
SYNC = "app.modules.ads.tasks.sync_ad_account_task"
CHANGE = "app.modules.ads.tasks.apply_change_task"
TODAY = "app.modules.metrics.tasks.sync_today_task"
NIGHT = "app.modules.metrics.tasks.sync_insights_task"


@pytest.fixture(autouse=True)
def providers(monkeypatch: pytest.MonkeyPatch) -> None:
    known = {GOOGLE_ACCOUNT: "google", META_ACCOUNT: "meta"}
    monkeypatch.setattr(task_routes, "account_provider", lambda pk: known[str(pk)])
    monkeypatch.setattr(task_routes, "change_provider", lambda pk: known[str(pk)])


def test_a_google_account_is_read_on_googles_own_queue() -> None:
    assert route_task(SYNC, (GOOGLE_ACCOUNT,), {}, {}) == {"queue": GOOGLE_SYNC_QUEUE}
    assert route_task(SYNC, (), {"ad_account_id": GOOGLE_ACCOUNT}, {}) == {
        "queue": GOOGLE_SYNC_QUEUE
    }


def test_a_meta_account_stays_where_it_was() -> None:
    assert route_task(SYNC, (META_ACCOUNT,), {}, {}) == {"queue": "sync"}
    assert route_task(CHANGE, (META_ACCOUNT,), {}, {}) == {"queue": "agent"}


def test_a_press_on_google_waits_behind_no_meta_work() -> None:
    assert route_task(CHANGE, (GOOGLE_ACCOUNT,), {}, {}) == {"queue": GOOGLE_QUEUE}


def test_a_lookup_that_fails_sends_the_task_the_usual_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_pk: uuid.UUID) -> str:
        raise RuntimeError("database away")

    monkeypatch.setattr(task_routes, "account_provider", broken)

    assert route_task(SYNC, (GOOGLE_ACCOUNT,), {}, {}) == {"queue": "sync"}
    assert route_task(SYNC, ("not-an-id",), {}, {}) == {"queue": "sync"}


def test_other_tasks_are_left_to_their_own_queue() -> None:
    assert route_task("app.modules.ads.tasks.sync_all_accounts", (), {}, {}) is None


def test_every_routed_task_exists_and_leaves_its_queue_to_the_router() -> None:
    # Celery lets a decorator's queue win over the router: one put back
    # would quietly send Google's runs to the shared queue again.
    for name in ROUTED:
        assert getattr(celery_app.tasks[name], "queue", None) is None, name


def test_googles_own_tasks_never_touch_the_shared_queues() -> None:
    for name, queue in {
        "app.modules.ads.tasks.prepare_google_launch_task": GOOGLE_QUEUE,
        "app.modules.ads.tasks.create_google_campaign_task": GOOGLE_QUEUE,
        "app.modules.ads.tasks.refresh_google_volumes_task": GOOGLE_SYNC_QUEUE,
        "app.modules.integrations.tasks.sync_google_accounts_task": GOOGLE_SYNC_QUEUE,
    }.items():
        assert celery_app.tasks[name].queue == queue, name


def test_metas_figures_wait_behind_no_mirror() -> None:
    # Measured on production, 2026-11-12: on the queue they shared, two
    # slots were 87 percent busy and a task waited ten minutes on average.
    assert route_task(TODAY, (META_ACCOUNT,), {}, {}) == {"queue": FIGURES_QUEUE}
    assert route_task(NIGHT, (META_ACCOUNT,), {}, {}) == {"queue": FIGURES_QUEUE}
    assert route_task(TODAY, (GOOGLE_ACCOUNT,), {}, {}) == {"queue": GOOGLE_SYNC_QUEUE}


def test_the_figures_queue_is_one_the_app_declares() -> None:
    assert FIGURES_QUEUE in {queue.name for queue in celery_app.conf.task_queues}


def test_a_sweeps_read_is_background_and_a_press_is_not() -> None:
    assert is_background(task=SYNC, queue="sync")
    assert is_background(task=TODAY, queue=FIGURES_QUEUE)
    assert not is_background(task=TODAY, queue="refresh")
    assert not is_background(task=CHANGE, queue="agent")


def test_every_background_task_exists() -> None:
    from app.common.meta_gate import BACKGROUND_TASKS

    for name in BACKGROUND_TASKS:
        assert name in celery_app.tasks, name


def test_the_stop_is_kept_in_the_shared_cache() -> None:
    gate = CacheGate()
    assert gate.stopped() is None

    gate.stop(91.0, 300)

    assert gate.stopped() == 91.0
