"""When the metrics tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.metrics.tasks"

SCHEDULE: Final = [
    Periodic("Bugungi raqamlarni yangilash", f"{TASKS}.sync_today_metrics", "10,40"),
    Periodic("Kunlik raqamlarni sinxronlash", f"{TASKS}.sync_all_metrics", "20"),
    Periodic(
        "Tugallanmagan tungi raqamlarni xabar qilish",
        f"{TASKS}.report_unfinished_figures_task",
        "37",
        "6",
    ),
    Periodic("Eski raqamlarni tozalash", f"{TASKS}.purge_old_figures_task", "20", "5"),
]
