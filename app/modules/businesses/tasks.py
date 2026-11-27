"""The businesses' workers: a new profile's kind, guessed from its page."""

from app.worker import celery_app, task_session


@celery_app.task(queue="agent", ignore_result=True)
def guess_business_kind_task(business_id: str) -> None:
    from app.modules.businesses.services.guess import guess_kind

    with task_session() as db:
        guess_kind(db, business_id=business_id)
        db.commit()
