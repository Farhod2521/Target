"""The journal of a board's settings: every column, reason, button and
rule the superuser adds, changes or takes off is kept with who did it and
what it read before and after.

A write is read twice (``snap`` before it, ``keep`` after it) and the two
readings are compared, so no write has to say what it changed."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.boards.constants import (
    BUTTON_DUE_LABELS,
    REASON_PURPOSE_LABELS,
    SETTING_ACTION_LABELS,
    SETTING_AREA_LABELS,
    Board,
    ReasonPurpose,
    SettingAction,
    SettingArea,
)
from app.modules.boards.models import (
    BoardButton,
    BoardColumn,
    BoardReason,
    BoardSettingEvent,
    ContactReason,
)

Snap = dict[str, dict[str, Any]]
_ORDER = "__order__"
NAME_MAX = 200
HISTORY_PAGE = 50

# What is compared of each thing, and how the journal names it.
_FIELDS: dict[SettingArea, dict[str, str]] = {
    SettingArea.COLUMN: {
        "label": "Nomi",
        "shown": "Doskada",
        "talked": "Gaplashilgan",
    },
    SettingArea.REASON: {
        "label": "Nomi",
        "note_required": "Izoh shart",
        "archived": "Arxivda",
    },
    SettingArea.BUTTON: {
        "label": "Yozuvi",
        "to": "Ustuni",
        "due": "Vaqt",
        "note_required": "Izoh shart",
    },
    SettingArea.RULE: {
        "on": "Yoqilgan",
        "sentence": "Qoida",
        "reason": "Sabab matni",
        "notify_text": "Xabar matni",
    },
}


def _columns(db: Session, board: Board) -> list[BoardColumn]:
    return list(
        db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board == str(board))
            .order_by(BoardColumn.position, BoardColumn.code)
        )
    )


def snap(db: Session, *, board: Board, area: SettingArea) -> Snap:
    """The board's settings of one kind as they read now."""
    from app.common.db import utcnow
    from app.modules.boards import buttons, reason_lists, selectors

    # A database built without the migrations is seeded on its first read:
    # done here, so the seeds are not read as the write's own changes.
    now = utcnow()
    selectors.ensure_board(db, board=board, now=now)
    buttons.ensure(db, now=now)
    reason_lists.ensure(db, now=now)
    db.flush()
    columns = _columns(db, board)
    names = {column.code: column.name for column in columns}
    if area == SettingArea.COLUMN:
        out: Snap = {
            column.code: {
                "name": column.name,
                "label": column.name,
                "shown": column.is_visible,
                "talked": column.is_talked,
            }
            for column in columns
        }
        out[_ORDER] = {
            "order": [column.code for column in columns if column.is_visible]
        }
        return out
    if area == SettingArea.REASON:
        out = {
            str(row.id): {
                "name": f"{REASON_PURPOSE_LABELS[ReasonPurpose(row.purpose)]}: "
                f"{row.name}",
                "label": row.name,
                "note_required": row.note_required,
                "archived": row.is_archived,
            }
            for row in db.scalars(
                select(BoardReason).where(BoardReason.board == str(board))
            )
        }
        if board == Board.SUPPORT:
            for reason in db.scalars(select(ContactReason)):
                out[str(reason.id)] = {
                    "name": f"Bog'lanib bo'lmadi: {reason.name}",
                    "label": reason.name,
                    "note_required": False,
                    "archived": reason.is_archived,
                }
        return out
    if area == SettingArea.BUTTON:
        out = {}
        for row in db.scalars(
            select(BoardButton).where(BoardButton.board == str(board))
        ):
            if row.action == buttons.GO_ACTION:
                label = row.label
            else:
                from app.modules.boards.constants import CardAction

                label = row.label or (
                    buttons.default_label(board, CardAction(row.action))
                    if row.action in CardAction.values
                    else row.action
                )
            column = names.get(row.column_code, row.column_code)
            out[str(row.id)] = {
                "name": f"«{column}» ustuni: {label}",
                "label": label,
                "to": names.get(row.to_column, row.to_column),
                "due": str(BUTTON_DUE_LABELS.get(row.due, row.due)),
                "note_required": row.note_required,
            }
        return out
    from app.modules.boards import rules

    view = rules.settings_view(db, board=board, may_edit=False)
    return {
        str(row["id"]): {
            "name": row["name"],
            "on": row["is_enabled"],
            "sentence": row["sentence"],
            "reason": row["reason"],
            "notify_text": row.get("notify_text", ""),
        }
        for row in view["rules"]
        if row["id"]
    }


def _said(value: Any) -> str:
    if isinstance(value, bool):
        return "ha" if value else "yo'q"
    text = str(value) if value is not None else ""
    return f"«{text}»" if text else "—"


def keep(
    db: Session,
    *,
    board: Board,
    area: SettingArea,
    before: Snap,
    actor_id: uuid.UUID,
    now: datetime,
) -> int:
    """What a write changed, kept: one line for each thing added, changed
    or taken off, and one for a new order of the columns."""
    after = snap(db, board=board, area=area)
    labels = _FIELDS[area]
    lines: list[tuple[SettingAction, str, str]] = []
    for key, new in after.items():
        if key == _ORDER:
            continue
        old = before.get(key)
        if old is None:
            lines.append((SettingAction.ADD, new["name"], ""))
            continue
        changed = [
            f"{label}: {_said(old.get(field))} → {_said(new.get(field))}"
            for field, label in labels.items()
            if old.get(field) != new.get(field)
        ]
        if changed:
            lines.append((SettingAction.EDIT, old["name"], "; ".join(changed)))
    lines.extend(
        (SettingAction.REMOVE, old["name"], "")
        for key, old in before.items()
        if key != _ORDER and key not in after
    )
    was = (before.get(_ORDER) or {}).get("order")
    now_order = (after.get(_ORDER) or {}).get("order")
    if was is not None and was != now_order and sorted(was) == sorted(now_order or []):
        lines.append((SettingAction.ORDER, "Ustunlar tartibi", ""))
    for action, name, body in lines:
        db.add(
            BoardSettingEvent(
                board=str(board),
                area=str(area),
                action=str(action),
                name=name[:NAME_MAX],
                body=body,
                actor_id=actor_id,
                created_at=now,
            )
        )
    if lines:
        db.commit()
    return len(lines)


def history(
    db: Session,
    *,
    board: Board,
    area: str = "",
    before: datetime | None = None,
    limit: int = HISTORY_PAGE,
) -> dict[str, Any]:
    """The newest changes of the board's settings first."""
    query = select(BoardSettingEvent).where(BoardSettingEvent.board == str(board))
    if area:
        query = query.where(BoardSettingEvent.area == area)
    if before is not None:
        query = query.where(BoardSettingEvent.created_at < before)
    rows = list(
        db.scalars(
            query.order_by(
                BoardSettingEvent.created_at.desc(), BoardSettingEvent.id
            ).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    people = {
        person.id: person
        for person in db.scalars(
            select(User).where(
                User.id.in_({row.actor_id for row in rows if row.actor_id})
            )
        )
    }

    def who(actor_id: uuid.UUID | None) -> str:
        person = people.get(actor_id) if actor_id else None
        return (person.full_name or person.email) if person is not None else ""

    return {
        "rows": [
            {
                "id": str(row.id),
                "area": row.area,
                "area_label": str(
                    SETTING_AREA_LABELS.get(SettingArea(row.area), row.area)
                    if row.area in SettingArea.values
                    else row.area
                ),
                "action": row.action,
                "action_label": str(
                    SETTING_ACTION_LABELS.get(SettingAction(row.action), row.action)
                    if row.action in SettingAction.values
                    else row.action
                ),
                "name": row.name,
                "body": row.body,
                "actor": who(row.actor_id),
                "at": row.created_at,
            }
            for row in rows
        ],
        "next_before": rows[-1].created_at if more and rows else None,
        "areas": [
            {"value": str(item), "label": str(SETTING_AREA_LABELS[item])}
            for item in SettingArea
        ],
    }
