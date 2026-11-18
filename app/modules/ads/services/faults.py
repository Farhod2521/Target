"""A launch or a press failed by our own fault: kept for the Developers with
what it was about, its reference written on the row.

Only codes ``failure_kinds`` calls ours; a Meta refusal or a passing one is
left alone. Commits.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.constants import LAUNCH_LOG_PREFIX
from app.modules.ads.failure_kinds import FailureKind, kind_of
from app.modules.ads.models import CampaignLaunch
from app.modules.audit.models import ActionLog
from app.modules.audit.services.faults import FAULT_KEY, report_fault


def launch_fault(
    db: Session,
    launch: CampaignLaunch,
    *,
    code: str,
    message: str,
    where: str,
    exc: BaseException | None = None,
) -> str:
    """Keep the launch's fault when it is ours; its reference, or ""."""
    if kind_of(code) != FailureKind.SYSTEM:
        return ""
    reference = report_fault(
        db,
        owner_id=launch.owner_id,
        code=code,
        message=message,
        where=where,
        subject=f"launch:{launch.id}",
        context=launch_context(db, launch),
        exc=exc,
    )
    if reference:
        db.refresh(launch)
        launch.error_detail = {**(launch.error_detail or {}), FAULT_KEY: reference}
        db.commit()
    return reference


def action_fault(
    db: Session,
    log: ActionLog,
    *,
    code: str,
    message: str,
    where: str,
    exc: BaseException | None = None,
) -> str:
    """Keep the press's fault when it is ours; its reference, or ""."""
    if kind_of(code) != FailureKind.SYSTEM:
        return ""
    reference = report_fault(
        db,
        owner_id=log.owner_id,
        code=code,
        message=message,
        where=where,
        subject=f"action:{log.id}",
        context=action_context(log),
        exc=exc,
    )
    if reference:
        db.refresh(log)
        log.result_payload = {**(log.result_payload or {}), FAULT_KEY: reference}
        db.commit()
    return reference


def launch_context(db: Session, launch: CampaignLaunch) -> dict[str, Any]:
    """What the launch was: its place in the run, the account and page, what
    was sent to Meta last and what came back."""
    db.refresh(launch)
    account = launch.ad_account
    page = launch.page
    sent = db.scalar(
        select(ActionLog.request_payload)
        .where(
            ActionLog.idempotency_key.startswith(f"{LAUNCH_LOG_PREFIX}:{launch.id}:")
        )
        .order_by(ActionLog.created_at.desc())
        .limit(1)
    )
    return {
        "launch_id": launch.id,
        "status": launch.status,
        "step": launch.step,
        "progress": launch.progress,
        "campaign_name": launch.campaign_name,
        "provider": launch.provider,
        "ad_account": {
            "id": account.id if account else None,
            "external_id": account.external_id if account else "",
            "name": account.name if account else "",
        },
        "page": {
            "id": page.id if page else None,
            "external_id": page.external_id if page else "",
            "name": page.name if page else "",
        },
        "goal": (launch.answers or {}).get("goal", ""),
        "daily_budget_minor": launch.daily_budget_minor,
        "currency": launch.currency,
        "error_code": launch.error_code,
        "error_message": launch.error_message,
        "error_detail": launch.error_detail or {},
        "created_refs": launch.created_refs or {},
        "dropped": launch.dropped or {},
        "started_at": launch.started_at,
        "finished_at": launch.finished_at,
        "sent": sent or {},
    }


def action_context(log: ActionLog) -> dict[str, Any]:
    """What the press was: on what, what was sent, what was there before and
    what came back."""
    return {
        "action_id": log.id,
        "action": log.action,
        "actor_type": log.actor_type,
        "provider": log.target_provider,
        "level": log.target_level,
        "external_id": log.target_external_id,
        "sent": log.request_payload or {},
        "before": log.previous_state or {},
        "answer": log.result_payload or {},
        "error_code": log.error_code,
        "error_message": log.error_message,
        "created_at": log.created_at,
    }
