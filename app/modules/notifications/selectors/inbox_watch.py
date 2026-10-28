"""The waiting list's lines about a group this product switched on.

What each step says and which buttons it carries, written once for the
screen and the phone alike - see :mod:`core.agent.launch_watch`.
"""

from datetime import datetime
from typing import cast

from adskit import ExternalRef, ProviderName
from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.agent.selectors.launch_watch import watched_groups
from app.modules.agent.selectors.watched import Watched
from app.modules.metrics.selectors.results import words_for
from app.modules.notifications.selectors.inbox_page import InboxPage
from app.modules.notifications.selectors.inbox_watch_running import running_body
from core.agent.launch_watch import Move, Stage, moved_budget
from core.inbox import InboxItem, ItemAction, Level, Subject

LEVEL_OF: dict[Stage, Level] = {
    "unstarted": "news",
    "in_review": "news",
    "quiet": "news",
    "idle": "decision",
    "stuck": "decision",
    "fruitless": "urgent",
    "stalled": "decision",
    "dry": "urgent",
    "dearer": "decision",
    "cheaper": "decision",
    "stopped": "urgent",
}


def watch_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """One line per new group on this page that something is due about."""
    return [
        _item(row)
        for row in watched_groups(
            db,
            owner=owner,
            accounts=view.accounts,
            now=now,
            hidden_adsets=view.scope.outside,
        )
    ]


def watch_title(row: Watched) -> str:
    """The line's heading, shared with the phone."""
    stage = row.watch.stage
    if stage == "unstarted":
        if row.in_review:
            return "Reklama Meta tekshiruvida"
        return "Ko'rsatish hali boshlanmadi"
    titles: dict[str, str] = {
        "in_review": "Meta tekshiruvi davom etyapti",
        "idle": "Reklama tasdiqlandi, lekin sarf yo'q",
        "stuck": "Reklama 48 soatdan beri boshlanmadi",
        "quiet": "Hozircha natija yo'q",
        "fruitless": "3 kunda natija bo'lmadi",
        "stalled": "Reklama to'xtab qoldi",
        "dearer": "Natija qimmatlashdi",
        "cheaper": "Natija arzonlashdi - byudjetni oshirish mumkin",
        "stopped": "Natija bo'lmagani uchun reklama to'xtatildi",
    }
    if stage == "dry" and row.running is not None:
        return "%(days)s kundan beri natija yo'q" % {"days": row.running.dry_days}
    return titles[stage]


def watch_body(row: Watched) -> str:
    """What is happening, why, and what to do - shared with the phone."""
    if row.running is not None:
        return running_body(row, row.running)
    if row.watch.stage == "stopped":
        return _stopped_body(row)
    figures = {
        "hours": row.hours,
        "spend": _money(row, row.spend_minor),
        "label": words_for(row.kind).label,
    }
    return _BODIES[_body_key(row)] % figures


def move_label(row: Watched, move: Move) -> str:
    """What one button says. The budget's carries the figure it sets."""
    if move in ("budget_up", "budget_down") and row.daily_budget_minor:
        new = _money(
            row,
            moved_budget(
                budget_minor=row.daily_budget_minor,
                move=move,
                step_pct=row.watch.step_pct,
            ),
        )
        figures = {"new": new, "pct": row.watch.step_pct}
        if move == "budget_up":
            return "Byudjet +%(pct)s%% (%(new)s)" % figures
        return "Byudjet -%(pct)s%% (%(new)s)" % figures
    labels: dict[str, str] = {
        "wait": "Kutish",
        "pause": "To'xtatish",
        "delete": "O'chirish",
        "resume": "Qayta yoqish",
    }
    return labels[move]


def delete_question(row: Watched) -> str:
    """Asked before the one press that cannot be taken back."""
    return (
        "«%(name)s» o'chirilsinmi? Uni qaytarib bo'lmaydi - kerak bo'lsa "
        "qaytadan yaratasiz."
    ) % {"name": row.name}


def watch_key(row: Watched) -> str:
    """The step is in the key, so each step is new exactly once."""
    key = f"watch:{row.adset_id}:{row.watch.stage}"
    return f"{key}:{row.watch.tag}" if row.watch.tag else key


def _item(row: Watched) -> InboxItem:
    return InboxItem(
        key=watch_key(row),
        kind="watch",
        level=LEVEL_OF[row.watch.stage],
        title=watch_title(row),
        body=watch_body(row),
        actions=tuple(
            action for move in row.watch.moves if (action := _action(row, move)).label
        ),
        subject=Subject(
            ref=ExternalRef(
                provider=cast("ProviderName", row.provider),
                level="adset",
                id=row.adset_id,
            ),
            name=row.name,
        ),
    )


def _action(row: Watched, move: Move) -> ItemAction:
    advised = move == row.watch.advised
    if move == "wait":
        # Nothing to press: said when advised, left out otherwise.
        return ItemAction(label="Tavsiya: kuting" if advised else "", advised=True)
    return ItemAction(
        label=move_label(row, move),
        href=reverse("agent:watch_act", args=[row.adset_id, move]),
        advised=advised,
        confirm=delete_question(row) if move == "delete" else "",
    )


def _stopped_body(row: Watched) -> str:
    """What was spent, that nothing came of it, and the way back."""
    figures = {
        "spend": _money(row, row.spend_minor),
        "label": words_for(row.kind).label,
    }
    said = "%(spend)s sarflandi, %(label)s: 0." % figures
    if row.daily_budget_minor:
        said = (
            "Kunlik byudjet %(budget)s, shundan %(spend)s sarflandi, %(label)s: 0."
        ) % {**figures, "budget": _money(row, row.daily_budget_minor)}
    advice = (
        "Pul behuda ketmasligi uchun guruhni o'zimiz to'xtatdik. Avval rasm "
        "yoki formani yangilash yaxshi. Shundayligicha qayta yoqsangiz, hisob "
        "noldan boshlanadi."
    )
    return f"{said} {advice}"


def _body_key(row: Watched) -> str:
    stage = row.watch.stage
    if stage == "unstarted":
        return "review" if row.in_review else "approved"
    return stage


def _money(row: Watched, amount_minor: int) -> str:
    return format_minor(amount_minor=amount_minor, currency=row.currency)


_BODIES: dict[str, str] = {
    "review": (
        "Yoqilganiga %(hours)s soat bo'ldi, Meta reklamani hali tekshiryapti. "
        "Tekshiruv odatda 24 soat, ba'zan 48 soatgacha davom etadi - bu "
        "odatiy holat. Biz kuzatyapmiz, hozir hech narsani o'zgartirmang."
    ),
    "approved": (
        "Yoqilganiga %(hours)s soat bo'ldi. Meta reklamani tasdiqladi, lekin "
        "ko'rsatish hali boshlanmadi - ba'zan bunga bir necha soat ketadi. "
        "Biz kuzatyapmiz, hozir hech narsani o'zgartirmang."
    ),
    "in_review": (
        "Yoqilganiga %(hours)s soat bo'ldi, Meta tekshiruvi hali tugamadi. "
        "Tekshiruv 48 soatgacha cho'zilishi mumkin - kutamiz. Shundan keyin "
        "ham boshlanmasa, nima qilishni aytamiz."
    ),
    "idle": (
        "Yoqilganiga %(hours)s soat bo'ldi. Meta reklamani tasdiqladi, lekin "
        "hali hech narsa sarflanmadi. Baho berish uchun ma'lumot yo'q, shuning "
        "uchun byudjetni o'zgartirmaymiz - kuzatishda davom etamiz. Shunday "
        "qolsa, auditoriyani kengaytiring yoki kreativni almashtiring."
    ),
    "stuck": (
        "Yoqilganiga %(hours)s soat bo'ldi, reklama hali ham ko'rsatilmadi. "
        "Ba'zan Meta reklamani tekshiruvda tiqilib qoldiradi - o'chirib, "
        "qaytadan yaratish odatda tez yechadi."
    ),
    "quiet": (
        "Yoqilganiga %(hours)s soat bo'ldi: %(spend)s sarflandi, %(label)s: 0. "
        "Birinchi kunlarda bu odatiy - Meta hali kimga ko'rsatishni "
        "o'rganyapti. Yana 48 soat kutamiz, hozir hech narsani o'zgartirmang."
    ),
    "fruitless": (
        "%(hours)s soatda %(spend)s sarflandi, %(label)s: 0. Meta o'rganish "
        "uchun yetarli vaqt oldi - bu reklamadan natija kutish pulni "
        "behuda sarflash bo'ladi. O'chirib, boshqa rasm yoki matn bilan "
        "qaytadan yarating."
    ),
}


__all__ = [
    "LEVEL_OF",
    "delete_question",
    "move_label",
    "watch_body",
    "watch_items",
    "watch_key",
    "watch_title",
]
