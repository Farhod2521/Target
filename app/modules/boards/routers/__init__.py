"""The office boards, version 2: ``/api/v2/office/...``. Version 1's sales
board is not read or changed here."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.backoffice.constants import ROLE_LABELS, Role
from app.modules.boards import selectors, services, view
from app.modules.boards.access import BoardStaff, Staff, access_for, works_on
from app.modules.boards.constants import (
    BOARD_LABELS,
    CLOSE_REASON_LABELS,
    COLUMN_CARDS,
    COLUMN_CARDS_MAX,
    Board,
    CardAction,
    CloseReason,
)
from app.modules.boards.schemas import (
    ActionIn,
    AssignIn,
    BoardViewOut,
    CardDetailOut,
    ColumnsOut,
    MeOut,
    NoteIn,
    ReasonOut,
    StaffListOut,
)

router = APIRouter(prefix="/office", tags=["office boards v2"])


@router.get("/me", responses={200: {"model": MeOut}})
def me(db: Db, user: Staff) -> dict[str, Any]:
    """Who is reading, which board opens for them and what they may do."""
    access = access_for(db, user)
    return {
        "user": {
            "id": str(user.id),
            "name": user.full_name or user.email,
            "email": user.email,
        },
        "roles": [
            {"value": str(role), "label": str(ROLE_LABELS[role])}
            for role in Role
            if str(role) in access.roles
        ],
        "is_superuser": bool(user.is_superuser),
        "boards": [
            {
                "code": str(board),
                "label": str(BOARD_LABELS[board]),
                "lead": access.leads_board(board),
            }
            for board in access.boards
        ],
        "default_board": str(access.boards[0]) if access.boards else None,
        "can": {
            "take": works_on(db, user, Board.SALES),
            "assign": bool(access.leads),
            "move": access.full,
            "columns": access.full,
            "staff": access.full,
        },
    }


@router.get("/boards/{board}/columns", responses={200: {"model": ColumnsOut}})
def columns(db: Db, staff: BoardStaff) -> dict[str, Any]:
    """The board's columns as this person sees them, in order."""
    selectors.ensure_board(db, board=staff.board, now=utcnow())
    db.commit()
    return {
        "board": str(staff.board),
        "live_since": selectors.live_since(db, board=staff.board),
        "columns": [
            {
                "code": column.code,
                "name": column.name,
                "position": column.position,
                "kind": column.kind,
                "is_final": column.is_final,
            }
            for column in selectors.columns_for(
                db, board=staff.board, access=staff.access
            )
        ],
    }


@router.get("/boards/{board}", responses={200: {"model": BoardViewOut}})
def board(
    db: Db,
    staff: BoardStaff,
    column: Annotated[
        str, Query(max_length=24, description="One column only, for its next page.")
    ] = "",
    q: Annotated[str, Query(max_length=100, description="Name, email or phone.")] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=COLUMN_CARDS_MAX)] = COLUMN_CARDS,
) -> dict[str, Any]:
    """The board as this person sees it: a sales manager only their own
    cards, the lead and Support everything on their board."""
    selectors.ensure_board(db, board=staff.board, now=utcnow())
    db.commit()
    return view.board_view(
        db,
        board=staff.board,
        user=staff.user,
        access=staff.access,
        column=column,
        search=q,
        offset=offset,
        limit=limit,
    )


@router.get("/boards/{board}/staff", responses={200: {"model": StaffListOut}})
def board_people(db: Db, staff: BoardStaff) -> dict[str, Any]:
    """Who a card on this board can be given to. For the board's lead."""
    if not staff.access.leads_board(staff.board):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return {"staff": view.board_staff(db, board=staff.board)}


@router.get("/boards/sales/reasons", responses={200: {"model": list[ReasonOut]}})
def close_reasons(staff: Staff) -> list[dict[str, str]]:
    """Why a Sales card is closed."""
    return [
        {"value": str(reason), "label": str(CLOSE_REASON_LABELS[reason])}
        for reason in CloseReason
    ]


@router.post("/sales/take", responses={200: {"model": CardDetailOut}})
def take(db: Db, user: Staff) -> dict[str, Any]:
    """«Lid olish»: the oldest lead nobody works yet becomes this manager's."""
    if not works_on(db, user, Board.SALES):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    now = utcnow()
    card = services.take_lead(db, manager=user, now=now)
    return view.card_detail(db, card=card, now=now)


def _card_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None


@router.get("/cards/{card_id}", responses={200: {"model": CardDetailOut}})
def card(db: Db, user: Staff, card_id: str) -> dict[str, Any]:
    """One card: the client, the buttons to show and the history."""
    found = services.card_for(
        db, card_id=_card_id(card_id), user=user, access=access_for(db, user)
    )
    return view.card_detail(db, card=found, now=utcnow())


@router.post("/cards/{card_id}/actions", responses={200: {"model": CardDetailOut}})
def press(db: Db, user: Staff, card_id: str, body: ActionIn) -> dict[str, Any]:
    """A button on the card. Only the buttons in its `actions` are accepted."""
    if body.action not in CardAction.values:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Noma'lum tugma."
        )
    now = utcnow()
    found = services.act(
        db,
        card_id=_card_id(card_id),
        user=user,
        access=access_for(db, user),
        action=CardAction(body.action),
        now=now,
        on=body.on,
        reason=body.reason,
        note=body.note,
    )
    return view.card_detail(db, card=found, now=now)


@router.post("/cards/{card_id}/notes", responses={200: {"model": CardDetailOut}})
def note(db: Db, user: Staff, card_id: str, body: NoteIn) -> dict[str, Any]:
    now = utcnow()
    found = services.add_note(
        db,
        card_id=_card_id(card_id),
        user=user,
        access=access_for(db, user),
        body=body.body,
        now=now,
    )
    return view.card_detail(db, card=found, now=now)


@router.post("/cards/{card_id}/assign", responses={200: {"model": CardDetailOut}})
def give(db: Db, user: Staff, card_id: str, body: AssignIn) -> dict[str, Any]:
    """The Sales lead gives the card to a manager, or back to Ishlanmagan."""
    now = utcnow()
    target = None
    if body.staff_id:
        try:
            target = uuid.UUID(body.staff_id)
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Xodim topilmadi."
            ) from None
    found = services.assign(
        db,
        card_id=_card_id(card_id),
        user=user,
        access=access_for(db, user),
        to_id=target,
        now=now,
    )
    return view.card_detail(db, card=found, now=now)
