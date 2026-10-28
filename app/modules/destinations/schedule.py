"""When the destinations tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.destinations.tasks"

SCHEDULE: Final = [
    Periodic(
        "Mijozlarni Google jadvalga yozish",
        f"{TASKS}.sweep_sheets_task",
        "*",
    ),
    Periodic(
        "Google jadvallarni tekshirish",
        f"{TASKS}.check_sheet_links_task",
        "35",
        "4",
    ),
]
