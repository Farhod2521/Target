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
    # The bank sets the day's rate in the afternoon; twice, so that one missed
    # answer is made up the same day (04:15 and 12:15 UTC).
    Periodic("Valyuta kurslarini o'qish", f"{TASKS}.store_rates_task", "15", "4,12"),
    Periodic("Eski raqamlarni tozalash", f"{TASKS}.purge_old_figures_task", "20", "5"),
]
