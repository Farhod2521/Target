"""Celery tasks for platform surveys."""

from app.worker import celery_app, task_session


@celery_app.task(queue="agent", ignore_result=True)
def translate_survey_task(survey_id: str, actor_id: str) -> str:
    """A saved survey's wording in every other language. With every other
    Claude call, and no retry: the office asks again with one press."""
    from app.modules.surveys.services.translate import translate_survey

    with task_session() as db:
        return translate_survey(db, survey_id=survey_id, actor_id=actor_id)
