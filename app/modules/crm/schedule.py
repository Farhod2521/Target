"""When the crm tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.crm.tasks"

SCHEDULE: Final = [
    Periodic(
        "CRM: tushmay qolgan lidlarni joylash",
        f"{TASKS}.sweep_unplaced_task",
        "5,15,25,35,45,55",
    ),
]
