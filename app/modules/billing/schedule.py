"""When the billing tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.billing.tasks"

SCHEDULE: Final = [
    Periodic("To'lanmagan hisoblarni yopish", f"{TASKS}.expire_invoices_task", "*/10"),
    Periodic(
        "Tashlab ketilgan to'lov urinishlarini bo'shatish",
        f"{TASKS}.release_stale_holds_task",
        "*/10",
    ),
]
