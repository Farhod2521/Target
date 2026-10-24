from typing import Literal

from telegramkit import Button

from app.common.routes import reverse
from app.modules.agent.selectors.launch_watch import Watched
from app.modules.notifications.constants import (
    CALLBACK_WATCH_DELETE,
    CALLBACK_WATCH_DELETE_SURE,
    CALLBACK_WATCH_DOWN,
    CALLBACK_WATCH_PAUSE,
    CALLBACK_WATCH_RESUME,
    CALLBACK_WATCH_UP,
    CALLBACK_WATCH_WAIT,
)
from app.modules.notifications.keys import pause_data
from app.modules.notifications.selectors.inbox_watch import (
    delete_question,
    move_label,
    watch_body,
    watch_title,
)
from app.modules.notifications.services.compose import (
    Message,
    _bold,
    _link,
    escaped,
    page_line,
)
from core.agent.launch_watch import Move

CALLBACK_OF: dict[Move, str] = {
    "budget_up": CALLBACK_WATCH_UP,
    "budget_down": CALLBACK_WATCH_DOWN,
    "pause": CALLBACK_WATCH_PAUSE,
    "delete": CALLBACK_WATCH_DELETE,
    "wait": CALLBACK_WATCH_WAIT,
    "resume": CALLBACK_WATCH_RESUME,
}


def watch_message(*, row: Watched, page: str = "") -> Message:
    lines = [
        *page_line(page),
        _bold(watch_title(row)),
        escaped(f"«{row.name}»"),
        "",
        escaped(watch_body(row)),
        "",
    ]
    if row.watch.stage != "stopped":
        advice = escaped(move_label(row, row.watch.advised))
        lines += [f"{_bold('Tavsiya')}: {advice}", ""]
    lines.append(_link(path=reverse("actions:home"), label="Kabinetda ochish"))
    return Message(text="\n".join(lines))


def watch_buttons(row: Watched) -> tuple[Button, ...]:
    return tuple(
        Button(
            text=move_label(row, move),
            data=pause_data(external_id=row.adset_id, action=CALLBACK_OF[move]),
            style=_style(row, move),
        )
        for move in row.watch.moves
    )


def delete_ask(row: Watched) -> tuple[Message, tuple[Button, ...]]:
    buttons = (
        Button(
            text="Ha, o'chirish",
            data=pause_data(
                external_id=row.adset_id, action=CALLBACK_WATCH_DELETE_SURE
            ),
            style="danger",
        ),
        Button(
            text="Yo'q",
            data=pause_data(external_id=row.adset_id, action=CALLBACK_WATCH_WAIT),
        ),
    )
    return (Message(text=escaped(delete_question(row))), buttons)


def acted_message(*, move: Move) -> Message:
    if move == "delete":
        head = "O'chirish so'raldi"
        body = "Reklama bir necha daqiqada o'chiriladi. Yangisini «Reklama yaratish» bo'limida qaytadan yarating."
    elif move == "resume":
        head = "Qayta yoqish so'raldi"
        body = "Guruh bir necha daqiqada qayta yoqiladi. Hisob noldan boshlanadi - yana natijasiz sarf bo'lsa, xabar beramiz."
    elif move == "pause":
        head = "To'xtatish so'raldi"
        body = "Guruh bir necha daqiqada to'xtaydi. Qayta yoqish kabinetda."
    else:
        head = "Byudjet o'zgartirildi"
        body = (
            "Yangi byudjet bir necha daqiqada kuchga kiradi. Kuzatishda davom etamiz."
        )
    lines = [_bold(head), "", escaped(body)]
    if move == "delete":
        lines += ["", _link(path=reverse("ads:launch_start"), label="Reklama yaratish")]
    return Message(text="\n".join(lines))


def waited_message() -> Message:
    return Message(
        text="\n".join(
            [
                _bold("Yaxshi, kutamiz"),
                "",
                escaped("Reklamani kuzatishda davom etamiz va kerak bo'lsa yozamiz."),
            ]
        )
    )


def _style(row: Watched, move: Move) -> Literal["success"] | None:
    return "success" if move == row.watch.advised else None


__all__ = [
    "CALLBACK_OF",
    "acted_message",
    "delete_ask",
    "waited_message",
    "watch_buttons",
    "watch_message",
]
