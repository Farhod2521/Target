from app.common.dates import localtime
from app.common.db import utcnow
from app.common.task_routes import GOOGLE_SYNC_QUEUE
from app.modules.leads import services
from app.modules.leads.services import signals
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
def sweep_lead_signals_task() -> int:
    with task_session() as db:
        return signals.sweep_lead_signals(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def report_signals_task(owner_id: str) -> str:
    with task_session() as db:
        return signals.report_signals(db, owner_id=owner_id, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def sweep_unimported_deliveries_task() -> int:
    with task_session() as db:
        return services.sweep_unimported_deliveries(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def report_unimported_deliveries_task() -> int:
    with task_session() as db:
        return services.report_unimported_deliveries(db, now=utcnow())


@celery_app.task(queue=GOOGLE_SYNC_QUEUE, ignore_result=True)
def sync_google_leads_task(ad_account_id: str) -> int:
    from app.modules.leads.services.google import sync_google_leads

    with task_session() as db:
        return sync_google_leads(db, ad_account_id=ad_account_id, now=utcnow())


@celery_app.task(queue=GOOGLE_SYNC_QUEUE, ignore_result=True)
def sync_all_google_leads_task() -> int:
    """One read per Google account, each its own task so one slow account
    holds up nobody else's leads."""
    from app.modules.leads.services.google import accounts_to_read

    with task_session() as db:
        found = accounts_to_read(db, now=utcnow())
    for account_id in found:
        sync_google_leads_task.delay(str(account_id))
    return len(found)
