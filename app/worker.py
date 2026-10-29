"""The Celery app: same queues and limits as the Django project.

uv run celery -A app.worker worker -Q sync,webhooks,chat,agent,upload,refresh
uv run celery -A app.worker beat

Beat is RedBeat: the schedule is each module's ``schedule.SCHEDULE``, kept in
Redis, and a lock there lets only one beat send it however many are started.
"""

import importlib
import logging
import pkgutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from celery import Celery, Task
from celery.schedules import crontab
from celery.signals import before_task_publish, task_postrun, task_prerun
from kombu import Queue
from sqlalchemy.orm import Session

from app.common.config import settings

# httpx writes every request URL at INFO, and Graph API and Bot API URLs carry
# the access token or the bot token in them.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

celery_app = Celery("targetolog")
celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_default_queue="sync",
    task_queues=(
        Queue("webhooks", routing_key="webhooks"),
        Queue("chat", routing_key="chat"),
        Queue("agent", routing_key="agent"),
        Queue("upload", routing_key="upload"),
        Queue("refresh", routing_key="refresh"),
        Queue("sync", routing_key="sync"),
    ),
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 2 * 60 * 60},
    task_time_limit=600,
    task_soft_time_limit=540,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    worker_max_tasks_per_child=200,
    worker_max_memory_per_child=400_000,
    result_expires=3600,
    worker_hijack_root_logger=False,
    task_always_eager=settings.celery_always_eager,
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=settings.celery_broker_url,
    beat_max_loop_interval=60,
    redbeat_lock_timeout=300,
)


@contextmanager
def task_session() -> Iterator[Session]:
    from app import models as _models  # noqa: F401
    from app.common.db import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def autodiscover() -> None:
    import app.modules as modules

    for module in pkgutil.iter_modules(modules.__path__):
        try:
            importlib.import_module(f"app.modules.{module.name}.tasks")
        except ModuleNotFoundError as exc:
            if exc.name != f"app.modules.{module.name}.tasks":
                raise


def beat_schedule() -> dict[str, dict[str, Any]]:
    """Every module's ``schedule.SCHEDULE``, in the shape beat reads."""
    import app.modules as modules

    entries: dict[str, dict[str, Any]] = {}
    for module in pkgutil.iter_modules(modules.__path__):
        path = f"app.modules.{module.name}.schedule"
        try:
            declared = importlib.import_module(path)
        except ModuleNotFoundError as exc:
            if exc.name != path:
                raise
            continue
        for entry in declared.SCHEDULE:
            if entry.name in entries:
                raise ValueError(f"Two schedule entries named {entry.name!r}")
            entries[entry.name] = {
                "task": entry.task,
                "schedule": crontab(
                    minute=entry.minute, hour=entry.hour, day_of_week=entry.day_of_week
                ),
            }
    return entries


@before_task_publish.connect
def _stamp(headers: dict[str, Any] | None = None, **_: Any) -> None:
    from app.common.task_timing import stamp_enqueued

    if headers is not None:
        stamp_enqueued(headers, now=time.time())


@task_prerun.connect
def _started(task: Task | None = None, **_: Any) -> None:
    from app.common.task_timing import STARTED_ATTR

    if task is not None and not task.request.is_eager:
        setattr(task.request, STARTED_ATTR, time.time())


@task_postrun.connect
def _finished(task: Task | None = None, state: str | None = None, **_: Any) -> None:
    from app.common.task_timing import ENQUEUED_HEADER, STARTED_ATTR, record_run

    if task is None:
        return
    request = task.request
    started = getattr(request, STARTED_ATTR, None)
    if started is None:
        return
    delivery = request.delivery_info or {}
    record_run(
        queue=str(delivery.get("routing_key") or task.queue or "sync"),
        task=str(task.name),
        enqueued_at=None if request.eta else getattr(request, ENQUEUED_HEADER, None),
        started_at=started,
        finished_at=time.time(),
        state=state or "",
    )


from app.bootstrap import register_providers  # noqa: E402

register_providers()
autodiscover()
celery_app.conf.beat_schedule = beat_schedule()
