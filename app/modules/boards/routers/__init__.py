"""The office boards, version 2: ``/api/v2/office/...``. Version 1's sales
board is not read or changed here."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.backoffice.constants import ROLE_LABELS, Role
from app.modules.boards import selectors
from app.modules.boards.access import BoardStaff, Staff, access_for
from app.modules.boards.constants import BOARD_LABELS, Board
from app.modules.boards.schemas import ColumnsOut, MeOut

router = APIRouter(prefix="/office", tags=["office boards v2"])


@router.get("/me", responses={200: {"model": MeOut}})
def me(db: Db, user: Staff) -> dict[str, Any]:
    """Who is reading, which board opens for them and what they may do."""
    access = access_for(db, user)
    sales = Board.SALES in access.boards
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
            "take": sales,
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
