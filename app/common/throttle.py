import hashlib
import logging
from typing import Final

from app.common.cache import cache

logger = logging.getLogger(__name__)
KEY: Final = "throttle:{bucket}:{digest}"
DIGEST_LENGTH: Final = 32


def _name(bucket: str, key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()[:DIGEST_LENGTH]
    return KEY.format(bucket=bucket, digest=digest)


def record(*, bucket: str, key: str, window_seconds: int) -> int:
    name = _name(bucket, key)
    try:
        cache.add(name, 0, timeout=window_seconds)
        return int(cache.incr(name))
    except ValueError:
        cache.set(name, 1, timeout=window_seconds)
        return 1
    except Exception:
        logger.warning("throttle %s unavailable, allowing through", bucket)
        return 0


def spent(*, bucket: str, key: str, limit: int) -> bool:
    try:
        used = int(cache.get(_name(bucket, key), 0))
    except Exception:
        logger.warning("throttle %s unreadable, allowing through", bucket)
        return False
    if used >= limit:
        logger.info("throttled %s at %s attempts", bucket, used)
        return True
    return False


def hit(*, bucket: str, key: str, limit: int, window_seconds: int) -> bool:
    used = record(bucket=bucket, key=key, window_seconds=window_seconds)
    if used > limit:
        logger.info("throttled %s after %s attempts", bucket, used)
        return False
    return True


def forget(*, bucket: str, key: str) -> None:
    try:
        cache.delete(_name(bucket, key))
    except Exception:
        logger.warning("throttle %s could not be cleared", bucket)
