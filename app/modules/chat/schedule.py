"""When the chat tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.chat.tasks"

SCHEDULE: Final = [
    Periodic(
        "Eskirgan chat suhbatlarini o'chirish",
        f"{TASKS}.sweep_chat_sessions",
        "40",
        "7",
    ),
    Periodic(
        "Javobsiz qolgan savollarni yopish",
        f"{TASKS}.sweep_stuck_answers_task",
        "6,16,26,36,46,56",
    ),
]
