import uuid

from app.common.db import utcnow
from app.modules.broadcasts.delivery import run
from app.modules.notifications import bot as telegram
from app.modules.notifications.exceptions import BotNotConfigured
from app.worker import celery_app, task_session


@celery_app.task(queue="broadcast", ignore_result=True)
def deliver_broadcast_task(broadcast_id: str) -> bool:
    """One run of a broadcast; queues the next while there is more."""
    with task_session() as db:
        try:
            with telegram.bot() as client:
                done = run(
                    db, client=client, broadcast_id=uuid.UUID(broadcast_id), now=utcnow
                )
        except BotNotConfigured:
            return False
    if done.more:
        deliver_broadcast_task.apply_async((broadcast_id,), countdown=done.wait)
    return done.more
