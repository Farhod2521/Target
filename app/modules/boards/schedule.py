"""When the boards' rules run on their own. UTC."""

from typing import Final

from app.common.periodic import Periodic

TASKS = "app.modules.boards.tasks"

SCHEDULE: Final = [
    Periodic(
        "Sotuv kanbani: yangi lidlar va sotilganlar",
        f"{TASKS}.sweep_sales_board_task",
        "*",
    ),
    Periodic(
        "Support kanbani: yangi zayavkalar",
        f"{TASKS}.sweep_support_board_task",
        "*",
    ),
    Periodic(
        "Support kanbani: reklamasi ishlamayotganlar",
        f"{TASKS}.sweep_idle_board_task",
        "15",
    ),
    Periodic(
        "Uzaytirish kanbani: tugayotgan obunalar",
        f"{TASKS}.sweep_renewal_board_task",
        "*",
    ),
]
