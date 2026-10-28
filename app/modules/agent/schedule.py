"""When the agent tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.agent.tasks"

SCHEDULE: Final = [
    Periodic(
        "Qotib qolgan ko'riklarni yopish", f"{TASKS}.release_stalled_runs_task", "13,43"
    ),
    Periodic(
        "Natijasiz sarf qilayotgan guruhlarni to'xtatish",
        f"{TASKS}.stop_all_fruitless",
        "19,49",
    ),
    Periodic(
        "To'xtagan reklamalarga tuzatish taklifi", f"{TASKS}.propose_all_fixes", "15,45"
    ),
    Periodic("Reklama guruhlari tashxisi", f"{TASKS}.diagnose_all_accounts_task", "50"),
    Periodic(
        "Tasdiqlangan o'zgarishlarni baholash",
        f"{TASKS}.assess_all_outcomes",
        "55",
        "5",
    ),
    Periodic("Agentni ishga tushirish", f"{TASKS}.run_all_agents", "0"),
]
