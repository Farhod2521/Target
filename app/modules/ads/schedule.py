"""When the ads tasks run on their own.

The names and minutes of Django's ``seed_schedules``, unchanged. They are
staggered on purpose: nothing heavy lands on :00 beside the half-hourly
sync, and the nightly passes sit in the quiet hours, apart from each other.
"""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.ads.tasks"

SCHEDULE: Final = [
    Periodic("Reklama akkauntlarini sinxronlash", f"{TASKS}.sync_all_accounts", "0,30"),
    Periodic(
        "Hamma akkauntlarni tunda sinxronlash",
        f"{TASKS}.sync_every_account_nightly",
        "50",
        "1",
    ),
    Periodic("Kreativ kutubxonasini sinxronlash", f"{TASKS}.sync_all_media", "40", "2"),
    Periodic(
        "Provayderda qolib ketgan obyektlarni tozalash",
        f"{TASKS}.sweep_stranded_launches_task",
        "23",
    ),
    Periodic(
        "Qotib qolgan tayyorlashlarni bo'shatish",
        f"{TASKS}.release_stalled_launches_task",
        "*/5",
    ),
    Periodic(
        "Tashlab ketilgan kutubxona yuklashlarini yopish",
        f"{TASKS}.sweep_abandoned_uploads_task",
        "6,36",
    ),
    Periodic(
        "Obunasi tugaganlarning reklamasini to'xtatish",
        f"{TASKS}.sweep_lapsed_subscriptions",
        "5,20,35,50",
    ),
    Periodic(
        "Reklama saytlarini tekshirish", f"{TASKS}.check_all_sites_task", "25", "3"
    ),
]
