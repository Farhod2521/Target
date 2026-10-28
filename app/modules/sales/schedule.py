"""When the sales tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.sales.tasks"

SCHEDULE: Final = [
    Periodic(
        "Sotuv kartalari muddatini yopish",
        f"{TASKS}.release_expired_claims_task",
        "7,22,37,52",
    ),
    Periodic("Sotuv oyini yopish", f"{TASKS}.close_sales_months_task", "25"),
]
