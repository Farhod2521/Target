import logging
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, Final

from app.common.cache import cache

logger = logging.getLogger(__name__)
ENQUEUED_HEADER: Final = "enqueued_at"
STARTED_ATTR: Final = "timing_started_at"
BUCKET_SECONDS: Final = 60 * 60
KEPT_HOURS: Final = 24
SLOW_WAIT_SECONDS: Final = 5 * 60
_KEY: Final = "tasktiming:{queue}:{bucket}:{field}"
_COUNT, _WAIT_SUM, _WAIT_MAX, _SLOW, _RUN_SUM = (
    "count",
    "wait_ms",
    "wait_max_ms",
    "slow",
    "run_ms",
)
_FIELDS: Final = (_COUNT, _WAIT_SUM, _WAIT_MAX, _SLOW, _RUN_SUM)


@dataclass(frozen=True, slots=True)
class Timing:
    count: int
    wait_ms_total: int
    wait_ms_max: int
    slow: int
    run_ms_total: int

    @property
    def wait_ms_average(self) -> int | None:
        return self.wait_ms_total // self.count if self.count else None

    @property
    def run_ms_average(self) -> int | None:
        return self.run_ms_total // self.count if self.count else None


def stamp_enqueued(headers: MutableMapping[str, Any], *, now: float) -> None:
    headers[ENQUEUED_HEADER] = now


def record_run(
    *,
    queue: str,
    task: str,
    enqueued_at: float | None,
    started_at: float,
    finished_at: float,
    state: str,
) -> None:
    run_ms = max(0, round((finished_at - started_at) * 1000))
    wait_ms = (
        None
        if enqueued_at is None
        else max(0, round((started_at - enqueued_at) * 1000))
    )
    logger.info(
        "task.timing",
        extra={
            "queue": queue,
            "task": task,
            "state": state,
            "wait_ms": wait_ms,
            "run_ms": run_ms,
        },
    )
    bucket = int(started_at // BUCKET_SECONDS)
    _add(queue, bucket, _RUN_SUM, run_ms)
    if wait_ms is None:
        return
    _add(queue, bucket, _COUNT, 1)
    _add(queue, bucket, _WAIT_SUM, wait_ms)
    if wait_ms >= SLOW_WAIT_SECONDS * 1000:
        _add(queue, bucket, _SLOW, 1)
    _raise_max(queue, bucket, wait_ms)


def recent_timing(*, queue: str, hours: int, now: float) -> Timing:
    newest = int(now // BUCKET_SECONDS)
    buckets = range(newest - hours + 1, newest + 1)
    keys = {
        (bucket, field): _key(queue, bucket, field)
        for bucket in buckets
        for field in _FIELDS
    }
    stored = cache.get_many(keys.values())

    def total(field: str) -> int:
        return sum(int(stored.get(keys[b, field], 0)) for b in buckets)

    def largest(field: str) -> int:
        return max((int(stored.get(keys[b, field], 0)) for b in buckets), default=0)

    return Timing(
        count=total(_COUNT),
        wait_ms_total=total(_WAIT_SUM),
        wait_ms_max=largest(_WAIT_MAX),
        slow=total(_SLOW),
        run_ms_total=total(_RUN_SUM),
    )


def _key(queue: str, bucket: int, field: str) -> str:
    return _KEY.format(queue=queue, bucket=bucket, field=field)


def _add(queue: str, bucket: int, field: str, amount: int) -> None:
    key = _key(queue, bucket, field)
    cache.add(key, 0, timeout=_kept_for())
    cache.incr(key, amount)


def _raise_max(queue: str, bucket: int, wait_ms: int) -> None:
    key = _key(queue, bucket, _WAIT_MAX)
    if wait_ms > int(cache.get(key, 0)):
        cache.set(key, wait_ms, timeout=_kept_for())


def _kept_for() -> int:
    return (KEPT_HOURS + 1) * BUCKET_SECONDS
