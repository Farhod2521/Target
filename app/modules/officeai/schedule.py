"""When the office assistant's tasks run on their own. UTC."""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.officeai.tasks"

SCHEDULE: Final = [
    Periodic(
        "Ofis AI: javobsiz qolgan savollarni yopish",
        f"{TASKS}.sweep_stuck_office_answers",
        "9,29,49",
    ),
]
