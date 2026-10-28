"""When the leads tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.leads.tasks"

SCHEDULE: Final = [
    Periodic(
        "Yetkazilmagan lidlarni yig'ish", f"{TASKS}.reconcile_all_pages_task", "40"
    ),
    Periodic(
        "Yiqilgan lid yetkazishlarini qayta o'qish",
        f"{TASKS}.retry_failed_deliveries_task",
        "8,23,38,53",
    ),
    Periodic(
        "O'qilmay qolgan lid yetkazishlarini o'qish",
        f"{TASKS}.sweep_unimported_deliveries_task",
        "14,44",
    ),
    Periodic(
        "Muddati o'tgan lid ma'lumotini o'chirish",
        f"{TASKS}.erase_expired_leads_task",
        "10",
        "7",
    ),
    Periodic(
        "Egasiz kelgan lidlar haqida xabar berish",
        f"{TASKS}.report_orphan_deliveries_task",
        "5",
        "8",
    ),
    Periodic(
        "O'qilmay qolgan lid yetkazishlari haqida xabar berish",
        f"{TASKS}.report_unimported_deliveries_task",
        "20",
        "8",
    ),
    Periodic(
        "Imzosi rad etilgan webhook xabarlarini o'chirish",
        f"{TASKS}.purge_raw_events_task",
        "55",
        "7",
    ),
    Periodic(
        "Lid natijalarini Meta'ga yuborish",
        f"{TASKS}.sweep_lead_verdicts_task",
        "20,50",
    ),
]
