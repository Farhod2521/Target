"""A launch's switch-on that never reached Meta is asked again, and only that."""

from datetime import timedelta

import pytest
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch, DeliveryStop
from app.modules.ads.services.creation import LATE_NOTE
from app.modules.ads.services.restart import MAX_RESTARTS, restart_launches, restarts
from app.modules.audit.models import ActionLog
from tests.pg.test_ads_manage import _mirror, _owner_with_account

REFS = {"campaign": "c_1", "adset": ["s_1"], "ad": ["a_1"]}


@pytest.fixture(autouse=True)
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.billing.services.require_live_subscription", lambda *_a, **_k: None
    )


def _launch(db: Session, **fields: object) -> tuple[User, CampaignLaunch]:
    owner, account = _owner_with_account(db)
    _mirror(db, owner, account.id)
    for row in (db.scalars(select(model)).one() for model in (Campaign, AdSet, Ad)):
        row.delivery, row.status = "paused", "PAUSED"
    finished = utcnow() - timedelta(hours=1)
    launch = CampaignLaunch(
        owner_id=owner.id,
        ad_account_id=account.id,
        provider=PROVIDER,
        status="created",
        created_refs=REFS,
        finished_at=finished,
        **fields,
    )
    db.add(launch)
    db.commit()
    return owner, launch


def _resume(
    owner: User, external_id: str, *, level: str, status: str, code: str = ""
) -> ActionLog:
    return ActionLog(
        owner_id=owner.id,
        actor_type="system",
        action="resume",
        target_level=level,
        target_external_id=external_id,
        target_provider=PROVIDER,
        idempotency_key=f"{external_id}-{status}-{code}",
        status=status,
        error_code=code,
        created_at=utcnow() - timedelta(minutes=50),
    )


def _restarted(db: Session) -> list[ActionLog]:
    return list(
        db.scalars(
            select(ActionLog).where(
                ActionLog.action == "resume", ActionLog.status == "pending"
            )
        )
    )


def test_a_launch_too_late_to_start_is_switched_on_again(
    db: Session, queued: list
) -> None:
    _owner, launch = _launch(db, delivery_note=LATE_NOTE)

    assert restart_launches(db, now=utcnow()) == 1

    db.refresh(launch)
    assert launch.delivery_note == ""
    assert launch.delivery_started_at is not None
    assert restarts(launch) == 1
    assert {log.target_level for log in _restarted(db)} == {"campaign", "adset", "ad"}


def test_a_resume_meta_dropped_for_a_passing_reason_is_sent_again(
    db: Session, queued: list
) -> None:
    owner, _launch_row = _launch(db, delivery_started_at=utcnow() - timedelta(hours=1))
    db.add_all(
        [
            _resume(owner, "c_1", level="campaign", status="failed", code="temporary"),
            _resume(owner, "s_1", level="adset", status="applied"),
            _resume(owner, "a_1", level="ad", status="failed", code="stalled"),
        ]
    )
    db.commit()

    assert restart_launches(db, now=utcnow()) == 1

    assert {log.target_external_id for log in _restarted(db)} >= {"c_1", "a_1"}


def test_a_refusal_with_a_reason_is_not_asked_again(db: Session, queued: list) -> None:
    owner, _launch_row = _launch(db, delivery_started_at=utcnow() - timedelta(hours=1))
    db.add(
        _resume(owner, "c_1", level="campaign", status="failed", code="account_blocked")
    )
    db.commit()

    assert restart_launches(db, now=utcnow()) == 0
    assert _restarted(db) == []


def test_what_the_owner_paused_is_left_off(db: Session, queued: list) -> None:
    owner, _launch_row = _launch(db, delivery_note=LATE_NOTE)
    paused = _resume(owner, "c_1", level="campaign", status="applied")
    paused.actor_type, paused.action = "user", "pause"
    db.add(paused)
    db.commit()

    assert restart_launches(db, now=utcnow()) == 0
    assert _restarted(db) == []


def test_what_ads_manager_stopped_is_left_off(db: Session, queued: list) -> None:
    owner, launch = _launch(db, delivery_note=LATE_NOTE)
    db.add(
        DeliveryStop(
            owner_id=owner.id,
            ad_account_id=launch.ad_account_id,
            level="campaign",
            external_id="c_1",
            campaign_external_id="c_1",
            reason="ads_manager",
            detected_at=utcnow(),
        )
    )
    db.commit()

    assert restart_launches(db, now=utcnow()) == 0


def test_a_launch_is_asked_again_only_so_many_times(db: Session, queued: list) -> None:
    _owner, launch = _launch(
        db, delivery_note=LATE_NOTE, draft={"restarts": MAX_RESTARTS}
    )

    assert restart_launches(db, now=utcnow()) == 0
    db.refresh(launch)
    assert launch.delivery_note == LATE_NOTE


def test_a_launch_still_in_its_own_switch_on_is_left_to_it(
    db: Session, queued: list
) -> None:
    _owner, launch = _launch(db, delivery_note=LATE_NOTE)
    launch.finished_at = utcnow() - timedelta(minutes=2)
    db.commit()

    assert restart_launches(db, now=utcnow()) == 0
