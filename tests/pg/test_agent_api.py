"""The agent over HTTP, and its nightly services on a cabinet with no figures."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.agent.constants import RunStatus, SkipReason, SuggestionStatus
from app.modules.agent.models import AgentRun, AgentSuggestion
from app.modules.agent.services import (
    assess_owner,
    check_frequency,
    diagnose_account,
    propose_fixes,
    release_stalled_runs,
    run_agent,
    stop_fruitless,
)
from app.modules.billing.services import start_trial
from tests.pg.conftest import sign_up
from tests.pg.test_cabinet_flows import _cabinet


def _owner(client: TestClient, db: Session) -> tuple[dict[str, str], User]:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    return auth, user


def _suggestion(db: Session, user: User, run: AgentRun) -> AgentSuggestion:
    row = AgentSuggestion(
        owner_id=user.id,
        run_id=run.id,
        kind="pause",
        rule="cpl_high",
        reason="Natija narxi odatdagidan ikki baravar qimmat.",
        target_provider=PROVIDER,
        target_level="adset",
        target_external_id="s_1",
        expires_at=utcnow() + timedelta(hours=48),
        status=SuggestionStatus.PENDING,
    )
    db.add(row)
    db.commit()
    return row


def test_agent_screens_and_answers(client: TestClient, db: Session) -> None:
    auth, user = _owner(client, db)

    waiting = client.get("/api/v1/agent", headers=auth)
    assert waiting.status_code == 200, waiting.text
    body = waiting.json()
    assert body["cards"] == [] and body["watch"] == [] and body["frequency"] == []

    saved = client.put(
        "/api/v1/agent/settings",
        json={
            "is_enabled": True,
            "self_repair": True,
            "window_days": 99,
            "cooldown_hours": 1,
            "max_per_run": 3,
            "budget_step_pct": 20,
        },
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["policy"]["window_days"] == 30
    assert saved.json()["policy"]["cooldown_hours"] == 12
    shown = client.get("/api/v1/agent/settings", headers=auth).json()
    assert shown["policy"]["self_repair"] is True and shown["limits"]["max_per_run"]

    run = AgentRun(owner_id=user.id, window_days=7, status=RunStatus.DONE)
    db.add(run)
    db.commit()
    row = _suggestion(db, user, run)
    rejected = client.post(f"/api/v1/agent/{row.id}/reject", headers=auth)
    assert rejected.status_code == 200, rejected.text
    db.refresh(row)
    assert row.status == SuggestionStatus.REJECTED
    again = client.post(f"/api/v1/agent/{row.id}/reject", headers=auth)
    assert again.status_code == 400

    history = client.get("/api/v1/agent/history", headers=auth)
    assert history.status_code == 200, history.text
    assert len(history.json()["history"]) == 1

    assert client.get("/api/v1/agent/verdicts", headers=auth).json() == {"rows": []}
    gone = client.post("/api/v1/agent/watch/s_1/pause", headers=auth)
    assert gone.status_code == 400
    missing = client.get(
        "/api/v1/agent/frequency/00000000-0000-0000-0000-000000000000/creative",
        headers=auth,
    )
    assert missing.status_code == 404


def test_the_night_on_a_cabinet_with_no_figures(
    client: TestClient, db: Session, queued: list
) -> None:
    _auth, user = _owner(client, db)
    now = utcnow()

    expired = run_agent(db, user=user)
    assert expired is not None and expired.skip_reason == SkipReason.EXPIRED

    start_trial(db, user=user, now=now)
    db.commit()
    account, _page = _cabinet(db, user)
    account.is_active = account.is_current = True
    db.commit()

    run = run_agent(db, user=user)
    assert run is not None and run.status == RunStatus.DONE
    assert run.skip_reason in {
        SkipReason.NO_ACCOUNT,
        SkipReason.STALE,
        SkipReason.NO_DATA,
    }

    assert diagnose_account(db, owner_id=str(user.id), now=now) == 0
    assert propose_fixes(db, owner=user, now=now) == 0
    assert stop_fruitless(db, owner=user, now=now) == 0
    assert check_frequency(db, owner=user, now=now) == []
    assert assess_owner(db, owner=user, now=now) == 0

    stuck = AgentRun(
        owner_id=user.id,
        window_days=7,
        status=RunStatus.RUNNING,
        created_at=now - timedelta(hours=2),
    )
    db.add(stuck)
    db.commit()
    assert release_stalled_runs(db) == 1
    db.refresh(stuck)
    assert stuck.status == RunStatus.FAILED


def test_the_readers_over_a_launched_group_with_figures(
    client: TestClient, db: Session
) -> None:
    from app.modules.ads.models import AdSet, CampaignLaunch
    from app.modules.agent.selectors.auto_stop import stop_candidates
    from app.modules.agent.selectors.facts import account_facts
    from app.modules.agent.selectors.frequency import frequency_candidates
    from app.modules.agent.selectors.launch_watch import watched_groups
    from app.modules.agent.selectors.same_day import burning_groups
    from app.modules.agent.selectors.strategy import strategy_state
    from app.modules.metrics.models import MetricsDaily, PeopleCount
    from core.agent import Policy
    from tests.pg.test_ads_manage import _mirror

    _auth, user = _owner(client, db)
    now = utcnow()
    start_trial(db, user=user, now=now)
    account, page = _cabinet(db, user)
    account.is_active = account.is_current = True
    page.is_current = page.is_active = True
    account.synced_at = now
    db.commit()
    _mirror(db, user, account.id)
    group = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert group is not None
    group.daily_budget_minor = 1_000
    group.optimization_goal_raw = "LEAD_GENERATION"
    db.add(
        CampaignLaunch(
            owner_id=user.id,
            ad_account_id=account.id,
            page_id=page.id,
            provider=PROVIDER,
            status="created",
            created_refs={"campaign": "c_1", "adset": ["s_1"], "ad": ["a_1"]},
            delivery_started_at=now - timedelta(days=10),
        )
    )
    zone = account.tzinfo()
    today = now.astimezone(zone).date()
    for back in range(0, 9):
        day = today - timedelta(days=back)
        db.add(
            MetricsDaily(
                owner_id=user.id,
                provider=PROVIDER,
                external_id="s_1",
                ad_account_id=account.id,
                level="adset",
                campaign_external_id="c_1",
                adset_external_id="s_1",
                date=day,
                spend_minor=900,
                currency="USD",
                impressions=4_000,
                clicks=40,
                inline_link_clicks=30,
                synced_at=now,
            )
        )
    db.add(
        PeopleCount(
            owner_id=user.id,
            provider=PROVIDER,
            external_id="s_1",
            ad_account_id=account.id,
            level="adset",
            adset_external_id="s_1",
            since=today - timedelta(days=7),
            until=today - timedelta(days=1),
            reach=5_000,
            synced_at=now,
        )
    )
    db.commit()

    facts = account_facts(db, owner=user, account=account, policy=Policy(), now=now)
    assert [item.external_id for item in facts.adsets] == ["s_1"]
    assert facts.adsets[0].week_frequency is not None
    state = strategy_state(db, owner=user, account=account, policy=Policy(), now=now)
    assert state.adsets
    watch = watched_groups(db, owner=user, accounts=[account], now=now)
    assert [row.adset_id for row in watch] == ["s_1"]
    stops = stop_candidates(db, owner=user, now=now)
    assert [row.group.adset_id for row in stops] == ["s_1"]
    assert stops[0].group.spend_minor > 0 and stops[0].results_ever == 0
    burning = burning_groups(db, owner=user, account=account, now=now)
    assert all(row.adset_id == "s_1" for row in burning)
    found = frequency_candidates(db, owner=user, now=now)
    assert all(row.reading.adset_id == "s_1" for row in found)

    from app.modules.agent.constants import AUTO_STOP_MARK
    from app.modules.audit.models import ActionLog

    assert stop_fruitless(db, owner=user, now=now) == 1
    log = db.scalar(select(ActionLog).where(ActionLog.target_external_id == "s_1"))
    assert log is not None and AUTO_STOP_MARK in log.request_payload
    assert "sarflandi" in log.reason


def test_frequency_is_read_at_nine_on_the_owner_s_clock_with_a_subscription(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from app.modules.agent import tasks

    _, user = _owner(client, db)
    account, _ = _cabinet(db, user)
    account.is_current = account.is_active = True
    db.commit()
    queued: list[str] = []
    monkeypatch.setattr(tasks, "task_session", contextmanager(lambda: iter([db])))
    monkeypatch.setattr(tasks.check_frequency_task, "delay", queued.append)

    # 04:05 UTC is 09:05 in Tashkent, the account's clock; 05:05 is ten.
    monkeypatch.setattr(
        tasks, "utcnow", lambda: datetime(2026, 10, 29, 5, 5, tzinfo=UTC)
    )
    assert tasks.check_all_frequency() == 0
    monkeypatch.setattr(
        tasks, "utcnow", lambda: datetime(2026, 10, 29, 4, 5, tzinfo=UTC)
    )
    assert tasks.check_all_frequency() == 1
    assert queued == [str(user.id)]

    monkeypatch.setattr(tasks, "check_frequency", lambda db, owner, now: [owner])
    assert tasks.check_frequency_task(str(user.id)) == 0
    start_trial(db, user=user, now=utcnow())
    assert tasks.check_frequency_task(str(user.id)) == 1
