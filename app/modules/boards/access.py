"""Who sees which board. Sales people see Sales, Support sees Support, the
renewal manager sees Uzaytirish, each their own cards; the Sales lead reads
Uzaytirish whole; the superuser and the Owner role see every board whole
and may change them."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.common.db import get_db
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.backoffice.permissions import roles_of, staff_required
from app.modules.boards.constants import (
    BOARD_ROLES,
    FULL_ROLES,
    LEAD_ROLES,
    WORKER_ROLES,
    Board,
)


@dataclass(frozen=True, slots=True)
class Access:
    roles: frozenset[str]
    boards: tuple[Board, ...]
    leads: frozenset[Board]
    full: bool

    def sees(self, board: Board) -> bool:
        return board in self.boards

    def leads_board(self, board: Board) -> bool:
        return board in self.leads


def access_of(*, roles: frozenset[str], is_superuser: bool) -> Access:
    """The boards these roles open. A superuser's roles are all of them."""
    full = is_superuser or any(str(role) in roles for role in FULL_ROLES)
    boards = tuple(
        board
        for board in Board
        if full or any(str(role) in roles for role in BOARD_ROLES[board])
    )
    leads = frozenset(
        board
        for board in boards
        if full or any(str(role) in roles for role in LEAD_ROLES[board])
    )
    return Access(roles=roles, boards=boards, leads=leads, full=full)


def access_for(db: Session, user: User) -> Access:
    return access_of(roles=roles_of(db, user), is_superuser=bool(user.is_superuser))


def works_on(db: Session, user: User, board: Board) -> bool:
    """Holds the board's own role: somebody cards can be given to. The
    superuser and the Owner see every board but are not on its team."""
    if not user.is_active or not user.is_staff or user.is_superuser:
        return False
    roles = roles_of(db, user)
    return any(str(role) in roles for role in WORKER_ROLES[board])


def may_take(db: Session, user: User) -> bool:
    """«Lid olish»: the Sales team, the superuser and the Owner."""
    if not user.is_active or not user.is_staff:
        return False
    if access_for(db, user).full:
        return True
    return works_on(db, user, Board.SALES)


def may_take_ticket(db: Session, user: User) -> bool:
    """«Zayavka olish»: the Support team, the superuser and the Owner."""
    if not user.is_active or not user.is_staff:
        return False
    if access_for(db, user).full:
        return True
    return works_on(db, user, Board.SUPPORT)


Staff = Annotated[User, Depends(staff_required(*Role))]


@dataclass(frozen=True, slots=True)
class OnBoard:
    user: User
    board: Board
    access: Access


def on_board(
    board: Annotated[str, Path(description="`sales`, `support` or `renewal`.")],
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OnBoard:
    """The board in the path, for staff who may open it; 404 for anybody
    else, as every office door answers."""
    staff = staff_required(*Role)(user=user, db=db)
    if board not in Board.values:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    access = access_for(db, staff)
    chosen = Board(board)
    if not access.sees(chosen):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return OnBoard(user=staff, board=chosen, access=access)


BoardStaff = Annotated[OnBoard, Depends(on_board)]
