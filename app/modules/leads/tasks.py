from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.leads import services
from app.worker import celery_app, task_session


@celery_app.task(queue="webhooks", ignore_result=True)
def import_lead_task(event_id: str) -> str:
    with task_session() as db:
        return services.import_lead(db, event_id=event_id)


@celery_app.task(queue="sync", ignore_result=True)
def retry_failed_deliveries_task() -> int:
    with task_session() as db:
        return services.retry_failed_deliveries(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def reconcile_page_task(page_id: str) -> int:
    with task_session() as db:
        return services.reconcile_page(db, page_id=page_id)


@celery_app.task(queue="sync", ignore_result=True)
def sync_page_forms_task(page_id: str) -> str:
    with task_session() as db:
        return services.refresh_page_forms(db, page_id=page_id)


@celery_app.task(queue="sync", ignore_result=True)
def reconcile_all_pages_task() -> int:
    with task_session() as db:
        return services.reconcile_all_pages(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def subscribe_page_task(page_id: str) -> str:
    with task_session() as db:
        return services.subscribe_page(db, page_id=page_id)


@celery_app.task(queue="sync", ignore_result=True)
def erase_expired_leads_task() -> int:
    with task_session() as db:
        return services.erase_expired_leads(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def report_orphan_deliveries_task() -> int:
    with task_session() as db:
        return services.report_orphan_deliveries(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def purge_raw_events_task() -> str:
    with task_session() as db:
        removed = services.purge_raw_events(
            db,
            before=services.unsigned_retention_floor(today=localtime(utcnow()).date()),
        )
    return f"purged:{removed}"


@celery_app.task(queue="sync", ignore_result=True)
def sweep_lead_verdicts_task() -> int:
    with task_session() as db:
        return services.sweep_lead_verdicts(db)


@celery_app.task(queue="sync", ignore_result=True)
def report_outcomes_task(owner_id: str) -> str:
    with task_session() as db:
        return services.report_outcomes(db, owner_id=owner_id)


@celery_app.task(queue="sync", ignore_result=True)
def sweep_unimported_deliveries_task() -> int:
    with task_session() as db:
        return services.sweep_unimported_deliveries(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def report_unimported_deliveries_task() -> int:
    with task_session() as db:
        return services.report_unimported_deliveries(db, now=utcnow())
