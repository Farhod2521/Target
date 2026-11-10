"""The office boards, version 2: ``/api/v2/office/...``. Version 1's sales
board is not read or changed here."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.backoffice.constants import ROLE_LABELS, Role
from app.modules.boards import help_options, selectors, services, view
from app.modules.boards import staff as staff_service
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
    ColumnsIn,
    ColumnsOut,
    HelpOptionsIn,
    HelpOptionsOut,
    MeOut,
    MoveIn,
    NoteIn,
    ReasonOut,
    StaffAddIn,
    StaffListOut,
    StaffPeopleOut,
    StaffPersonOut,
    StaffRolesIn,
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


def _full(db: Db, user: Staff) -> None:
    if not access_for(db, user).full:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.get(
    "/surveys/questions/{question_id}/help-options",
    responses={200: {"model": HelpOptionsOut}},
)
def survey_help(db: Db, user: Staff, question_id: str) -> dict[str, Any]:
    """The question's options, with the ones that ask for a specialist.
    For the superuser and the Owner."""
    _full(db, user)
    return help_options.help_options(db, question_id=_card_id(question_id))


@router.put(
    "/surveys/questions/{question_id}/help-options",
    responses={200: {"model": HelpOptionsOut}},
)
def set_survey_help(
    db: Db, user: Staff, question_id: str, body: HelpOptionsIn
) -> dict[str, Any]:
    """Mark the options that open a Support ticket when chosen."""
    _full(db, user)
    return help_options.set_help_options(
        db, question_id=_card_id(question_id), indexes=body.options, user=user
    )


@router.patch("/boards/{board}/columns", responses={200: {"model": ColumnsOut}})
def edit_columns(db: Db, staff: BoardStaff, body: ColumnsIn) -> dict[str, Any]:
    """Rename and reorder the board's columns. For the superuser and the
    Owner. Send every visible column, in the order wanted."""
    if not staff.access.full:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    now = utcnow()
    selectors.ensure_board(db, board=staff.board, now=now)
    selectors.rename_and_order(
        db,
        board=staff.board,
        columns=[(item.code, item.name) for item in body.columns],
        actor_id=staff.user.id,
        now=now,
    )
    return columns(db, staff)


@router.post("/cards/{card_id}/move", responses={200: {"model": CardDetailOut}})
def move_card(db: Db, user: Staff, card_id: str, body: MoveIn) -> dict[str, Any]:
    """Put a card in any visible column of its board, with the reason. For
    the superuser and the Owner."""
    now = utcnow()
    found = services.move_by_hand(
        db,
        card_id=_card_id(card_id),
        user=user,
        access=access_for(db, user),
        to=body.column,
        reason=body.reason,
        now=now,
    )
    return view.card_detail(db, card=found, now=now)


@router.get("/staff", responses={200: {"model": StaffPeopleOut}})
def staff_people(db: Db, user: Staff) -> dict[str, Any]:
    """Everybody on the staff with their roles. For the superuser and the Owner."""
    _full(db, user)
    return {"people": staff_service.staff_list(db)}


@router.get("/staff/search", responses={200: {"model": StaffPeopleOut}})
def staff_search(
    db: Db, user: Staff, q: Annotated[str, Query(min_length=3, max_length=100)]
) -> dict[str, Any]:
    """Signed-up accounts not on the staff yet, by email, phone or name."""
    _full(db, user)
    return {"people": staff_service.search_accounts(db, q=q)}


@router.post(
    "/staff",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": StaffPersonOut}},
)
def staff_add(db: Db, user: Staff, body: StaffAddIn) -> dict[str, Any]:
    """Make a signed-up account staff with these roles."""
    _full(db, user)
    return staff_service.add_staff(
        db, user_id=_card_id(body.user_id), roles=body.roles, actor=user
    )


@router.patch("/staff/{member_id}", responses={200: {"model": StaffPersonOut}})
def staff_roles(
    db: Db, user: Staff, member_id: str, body: StaffRolesIn
) -> dict[str, Any]:
    """The member's whole set of roles."""
    _full(db, user)
    return staff_service.change_roles(
        db, member_id=_card_id(member_id), roles=body.roles, actor=user
    )


@router.delete("/staff/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def staff_remove(db: Db, user: Staff, member_id: str) -> None:
    """Off the staff: the roles go and the account is a customer again."""
    _full(db, user)
    staff_service.remove_staff(db, member_id=_card_id(member_id), actor=user)
