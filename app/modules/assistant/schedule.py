"""When the one chat's tasks run on their own. UTC."""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.assistant.tasks"

SCHEDULE: Final = [
    Periodic(
        "AI chat: javobsiz qolgan savollarni yopish",
        f"{TASKS}.sweep_stuck_assistant_answers",
        "8,18,28,38,48,58",
    ),
]
