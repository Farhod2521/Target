"""When the audit tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.audit.tasks"

SCHEDULE: Final = [
    Periodic(
        "Yakunlanmagan o'zgarishlar haqida xabar berish",
        f"{TASKS}.report_unresolved_actions_task",
        "30",
        "8",
    ),
    Periodic(
        "Eskirgan xatolik yozuvlarini o'chirish",
        f"{TASKS}.purge_errors_task",
        "45",
        "7",
    ),
]
