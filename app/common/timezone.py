"""The handful of ``django.utils.timezone`` calls ported code still makes.

Django ran with USE_TZ and TIME_ZONE="UTC"; "local" meant the office zone.
"""

from datetime import UTC, date, datetime, tzinfo

from app.common.dates import localtime as _localtime
from app.common.dates import office_zone
from app.common.db import utcnow


def now() -> datetime:
    return utcnow()


def localtime(value: datetime | None = None, timezone: tzinfo | None = None) -> datetime:
    return _localtime(value or utcnow(), timezone)


def localdate(value: datetime | None = None, timezone: tzinfo | None = None) -> date:
    return localtime(value, timezone).date()


def get_current_timezone() -> tzinfo:
    return office_zone()


def make_aware(value: datetime, timezone: tzinfo | None = None) -> datetime:
    return value.replace(tzinfo=timezone or office_zone())


def is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


utc = UTC
