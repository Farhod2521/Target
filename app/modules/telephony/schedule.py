"""When telephony works on its own. UTC."""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.telephony.tasks"

SCHEDULE: Final = [
    Periodic(
        "Telefoniya: tushib qolgan qo'ng'iroqlar",
        f"{TASKS}.backfill_calls_task",
        "7",
    ),
    Periodic(
        "Telefoniya: eski hodisalarni o'chirish",
        f"{TASKS}.forget_hook_events_task",
        "35",
        "22",
    ),
]
