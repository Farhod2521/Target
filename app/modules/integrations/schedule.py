"""When the integrations tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.integrations.tasks"

SCHEDULE: Final = [
    Periodic(
        "Meta tokenlarini yangilash", f"{TASKS}.refresh_expiring_tokens", "17", "3"
    ),
    Periodic("Auditoriyalarni sinxronlash", f"{TASKS}.sync_all_audiences", "44", "3"),
    Periodic(
        "Piksel hodisalarini sinxronlash", f"{TASKS}.sync_all_pixel_events", "8", "4"
    ),
    Periodic(
        "Lid kelayotgan akkauntni topish",
        f"{TASKS}.discover_all_lead_accounts_task",
        "55",
    ),
    Periodic(
        "Oyna eskirganini tekshirish", f"{TASKS}.report_stale_mirror_task", "27,57"
    ),
]
