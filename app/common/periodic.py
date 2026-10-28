"""One entry of the beat schedule, as each module declares it.

A module that has work to do on a clock lists it in its own ``schedule.py``
as ``SCHEDULE``; ``app.worker`` collects them all. The fields are the ones
Django's ``seed_schedules`` wrote into ``django_celery_beat``, so an entry
ported from there reads the same. Minutes and hours are UTC.
"""

from typing import NamedTuple


class Periodic(NamedTuple):
    name: str
    task: str
    minute: str
    hour: str = "*"
    day_of_week: str = "*"
