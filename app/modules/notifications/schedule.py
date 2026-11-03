"""When the notification tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged, all UTC.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.notifications.tasks"

SCHEDULE: Final = [
    # Off the hour, so it is not queued behind the mirror's fan-out.
    Periodic(
        "Telegram bildirishnomalarini yuborish",
        f"{TASKS}.deliver_notices_task",
        "3,18,33,48",
    ),
    # 05:00 UTC is ten in the morning in the market this deployment sells to.
    Periodic(
        "Obuna tugashi haqida ogohlantirish",
        f"{TASKS}.deliver_expiry_notices_task",
        "0",
        "5",
    ),
    # Five minutes behind the lapse sweep that stops the adverts.
    Periodic(
        "Obuna tugagani haqida xabar berish",
        f"{TASKS}.deliver_lapse_notices_task",
        "10,25,40,55",
    ),
    # A minute past every hour: the report's hour is seven on the owner's
    # clock, and the weekly one a minute behind it on their Monday.
    Periodic(
        "Kunlik xisobotni Telegramga yuborish",
        f"{TASKS}.deliver_daily_reports_task",
        "1",
    ),
    Periodic(
        "Haftalik xisobotni Telegramga yuborish",
        f"{TASKS}.deliver_weekly_reports_task",
        "2",
    ),
    # Eleven past the hour, a minute no other hourly job uses.
    Periodic("So'rovnomani Telegramda so'rash", f"{TASKS}.deliver_surveys_task", "11"),
    Periodic(
        "To'lov chekini guruhga yuborish",
        f"{TASKS}.send_payment_receipts_task",
        "*",
    ),
    # Five past the hour; it writes only in the office's first hours after
    # midnight, so the zone it is read in may change without moving this.
    Periodic(
        "To'lovlar hisobotini guruhga yuborish",
        f"{TASKS}.send_payment_reports_task",
        "5",
    ),
    Periodic(
        "Kabinetdagi muammolar haqida xabar berish",
        f"{TASKS}.deliver_trouble_notices_task",
        "20",
    ),
]
