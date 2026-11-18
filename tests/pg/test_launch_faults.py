"""A launch failed by our own fault is the Developers', with what it was."""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.services import creation, rollback
from app.modules.audit.models import ErrorEvent
from tests.pg.test_office_team import _failed


def test_a_crash_while_creating_is_kept_with_its_traceback(
    db: Session, queued: list[tuple[str, tuple[object, ...]]]
) -> None:
    launch = _failed(db, status="creating")
    try:
        raise ValueError("budget is None")
    except ValueError as exc:
        creation._fail(db, launch, code="unknown", message=str(exc), exc=exc)

    fault = db.scalars(select(ErrorEvent)).one()
    assert fault.where == "ads.creation"
    assert fault.path == f"launch:{launch.id}"
    assert "budget is None" in fault.trace
    assert fault.context["status"] == "failed"
    db.refresh(launch)
    assert launch.error_detail["fault"] == fault.reference


def test_a_refusal_while_creating_is_not_a_fault(
    db: Session, queued: list[tuple[str, tuple[object, ...]]]
) -> None:
    launch = _failed(db, status="creating")
    creation._fail(db, launch, code="payment_missing", message="no card")

    assert db.scalar(select(ErrorEvent.id)) is None
    assert queued == [] or all(
        not name.endswith("deliver_fault_task") for name, _ in queued
    )


def test_a_launch_no_worker_finished_is_kept(
    db: Session, queued: list[tuple[str, tuple[object, ...]]]
) -> None:
    launch = _failed(db, status="creating", step="adset")
    db.execute(
        update(CampaignLaunch)
        .where(CampaignLaunch.id == launch.id)
        .values(started_at=utcnow() - timedelta(hours=2))
    )
    db.commit()

    assert rollback.release_stalled_launches(db) == 1

    fault = db.scalars(select(ErrorEvent)).one()
    assert fault.context["code"] == "stalled"
    assert "step adset" in fault.message
    db.refresh(launch)
    assert (launch.error_code, launch.error_detail["fault"]) == (
        "stalled",
        fault.reference,
    )
