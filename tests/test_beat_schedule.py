import logging

import pytest

from app.common.config import settings
from app.modules.ads.checks import rehearsing, warn_if_rehearsing
from app.worker import beat_schedule, celery_app


def test_beat_is_redbeat_and_carries_the_schedule() -> None:
    assert celery_app.conf.beat_scheduler == "redbeat.RedBeatScheduler"
    assert celery_app.conf.beat_schedule == beat_schedule()
    assert celery_app.conf.redbeat_lock_timeout > celery_app.conf.beat_max_loop_interval


def test_every_scheduled_task_exists() -> None:
    missing = [
        entry["task"]
        for entry in beat_schedule().values()
        if entry["task"] not in celery_app.tasks
    ]

    assert missing == []


def test_the_ads_tasks_keep_django_s_minutes() -> None:
    times = {
        entry["task"].rsplit(".", 1)[1]: (
            entry["schedule"]._orig_minute,
            entry["schedule"]._orig_hour,
        )
        for entry in beat_schedule().values()
        if entry["task"].startswith("app.modules.ads.")
    }

    assert times == {
        "sync_all_accounts": ("0,30", "*"),
        "sync_every_account_nightly": ("50", "1"),
        "sync_all_media": ("40", "2"),
        "sweep_stranded_launches_task": ("23", "*"),
        "release_stalled_launches_task": ("*/5", "*"),
        "sweep_abandoned_uploads_task": ("6,36", "*"),
        "sweep_lapsed_subscriptions": ("5,20,35,50", "*"),
        "check_all_sites_task": ("25", "3"),
    }


def test_the_sheet_tasks_keep_django_s_minutes() -> None:
    times = {
        name: (entry["schedule"]._orig_minute, entry["schedule"]._orig_hour)
        for name, entry in beat_schedule().items()
        if entry["task"].startswith("app.modules.destinations.")
    }

    assert times == {
        "Mijozlarni Google jadvalga yozish": ("*", "*"),
        "Google jadvallarni tekshirish": ("35", "4"),
    }


def test_a_debug_machine_may_rehearse_quietly() -> None:
    debug = settings.model_copy(update={"debug": True, "ads_dry_run": True})

    assert rehearsing(debug) == []


def test_a_deployment_that_rehearses_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    deployed = settings.model_copy(
        update={"debug": False, "ads_dry_run": True, "google_ads_dry_run": False}
    )

    with caplog.at_level(logging.WARNING, logger="app.modules.ads.checks"):
        warn_if_rehearsing(deployed)

    assert rehearsing(deployed) == ["ADS_DRY_RUN"]
    assert "ADS_DRY_RUN is on" in caplog.text


def test_both_switches_are_named(caplog: pytest.LogCaptureFixture) -> None:
    deployed = settings.model_copy(
        update={"debug": False, "ads_dry_run": True, "google_ads_dry_run": True}
    )

    with caplog.at_level(logging.WARNING, logger="app.modules.ads.checks"):
        warn_if_rehearsing(deployed)

    assert "ADS_DRY_RUN and GOOGLE_ADS_DRY_RUN are on" in caplog.text


def test_a_deployment_that_spends_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    live = settings.model_copy(
        update={"debug": False, "ads_dry_run": False, "google_ads_dry_run": False}
    )

    with caplog.at_level(logging.WARNING, logger="app.modules.ads.checks"):
        warn_if_rehearsing(live)

    assert caplog.text == ""
