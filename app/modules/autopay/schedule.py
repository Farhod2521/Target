"""When autopay runs on its own. UTC."""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.autopay.tasks"

SCHEDULE: Final = [
    # Hourly; each card is tried at most once a day, three times a term.
    Periodic("Obunani kartadan avtomatik yangilash", f"{TASKS}.charge_due_task", "25"),
]
