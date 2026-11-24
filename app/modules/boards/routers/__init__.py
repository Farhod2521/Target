"""The office boards, version 2: ``/api/v2/office/...``. Version 1's sales
board is not read or changed here."""

import functools
import logging
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, Db
from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ADMIN_ROLES, ROLE_LABELS, Role
from app.modules.backoffice.services import seen
from app.modules.boards import (
    buttons,
    client,
    columns_report,
    developer,  # noqa: F401 - closes a ticket when its fault is settled
    help_options,
    kinds,
    phone_take,
    reason_lists,
    renewal,
    rules,
    sales_kinds,
    selectors,
    services,
    settings_log,
    support_report,
    view,
)
from app.modules.boards import sales_report as sales_report_module
from app.modules.boards import staff as staff_service
from app.modules.boards.access import (
    BoardStaff,
    Staff,
    access_for,
    may_take,
    may_take_ticket,
)
from app.modules.boards.constants import (
    BOARD_LABELS,
    BOARD_MAIN_PURPOSE,
    COLUMN_CARDS,
    COLUMN_CARDS_MAX,
    COLUMNS_MAX,
    REPORT_DEFAULT_DAYS,
    Board,
    SettingArea,
    is_default_column_name,
)
from app.modules.boards.models import ContactReason
from app.modules.boards.schemas import (
    ActionIn,
    AssignIn,
    BoardViewOut,
    ButtonAddIn,
    ButtonEditIn,
    ButtonResetIn,
    ButtonsOut,
    CardAddIn,
    CardClientOut,
    CardDetailOut,
    ClientsFoundOut,
    ColumnAddIn,
    ColumnRemovalOut,
    ColumnsIn,
    ColumnsOut,
    ColumnsReportOut,
    ColumnTalkedIn,
    ContactReasonIn,
    ContactReasonOut,
    ContactReasonsOut,
    DueIn,
    HelpOptionsIn,
    HelpOptionsOut,
    MeOut,
    MoveIn,
    NoteIn,
    PhoneTakeIn,
    ReasonAddIn,
    ReasonEditIn,
    ReasonListsOut,
    ReasonOut,
    ReasonRowOut,
    RenewalManagerIn,
    RenewalManagerOut,
    RenewalReportOut,
    RuleAddIn,
    RuleEditIn,
    RulePreviewIn,
    RulePreviewOut,
    RulesOut,
    SalesKindsIn,
    SalesKindsOut,
    SalesReportOut,
    SettingsHistoryOut,
    StaffAddIn,
    StaffListOut,
    StaffPeopleOut,
    StaffPersonOut,
    StaffRolesIn,
    SupportKindsIn,
    SupportKindsOut,
    SupportMemberKindsOut,
    SupportReportOut,
    TicketAnswerIn,
    TicketAnswerOut,
    TicketQuestionStateOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/office", tags=["office boards v2"])


def _journaled(area: SettingArea) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """A settings write whose change is kept in the board's journal: the
    settings are read before and after it, and what differs is written with
    who did it (``settings_log``). A refused write changes nothing and
    keeps nothing."""

    def wrap(endpoint: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(endpoint)
        def inner(*args: Any, **kwargs: Any) -> Any:
            db = kwargs["db"]
            staff = kwargs.get("staff")
            board = staff.board if staff is not None else Board.SUPPORT
            actor = staff.user if staff is not None else kwargs["user"]
            before = settings_log.snap(db, board=board, area=area)
            out = endpoint(*args, **kwargs)
            settings_log.keep(
                db,
                board=board,
                area=area,
                before=before,
                actor_id=actor.id,
                now=utcnow(),
            )
            return out

        return inner

    return wrap


# The client's side: the one question Support asks them.
client_router = APIRouter(prefix="/support-ticket", tags=["support ticket"])


@client_router.get("", responses={200: {"model": TicketQuestionStateOut}})
def ticket_question(db: Db, user: CurrentUser) -> dict[str, Any]:
    """Whether «Muammoyingiz hal bo'ldimi?» waits for this client. The same
    question goes to their Telegram; the cabinet shows it until answered."""
    from app.modules.boards import confirm

    card = confirm.pending(db, owner_id=user.id)
    if card is None:
        return {"question": None}
    return {
        "question": {
            "asked_at": card.column_since,
            "expires_at": confirm.expires_at(card),
        }
    }


@client_router.post("/answer", responses={200: {"model": TicketAnswerOut}})
def ticket_answer(db: Db, user: CurrentUser, body: TicketAnswerIn) -> dict[str, str]:
    """The client's «Ha» or «Yo'q». Yes closes the ticket; no gives it back
    to the Support member who worked it."""
    from app.modules.boards import confirm

    return {
        "result": confirm.answer(
            db,
            owner_id=user.id,
            solved=body.solved,
            via=confirm.VIA_SITE,
            now=utcnow(),
        )
    }


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
            "take": may_take(db, user),
            "take_ticket": may_take_ticket(db, user),
            "assign": bool(access.leads),
            "move": access.full,
            "add_lead": access.leads_board(Board.SALES),
            "add_ticket": access.sees(Board.SUPPORT),
            "columns": access.full,
            "edit_columns": bool(user.is_superuser),
            "staff": access.full,
            "telephony": access.full,
            "client_card": bool(user.is_superuser)
            or any(str(role) in access.roles for role in ADMIN_ROLES),
            "sales_client_card": access.sees(Board.SALES),
            "renewal_manager": access.full,
        },
    }


@router.get("/boards/{board}/columns", responses={200: {"model": ColumnsOut}})
def columns(db: Db, staff: BoardStaff) -> dict[str, Any]:
    """The board's columns as this person sees them, in order."""
    selectors.ensure_board(db, board=staff.board, now=utcnow())
    db.commit()
    board_code = str(staff.board)
    markable = selectors.markable_columns(db, board=staff.board)

    def out(column: selectors.ColumnView) -> dict[str, Any]:
        return {
            "code": column.code,
            "name": column.name,
            "position": column.position,
            "kind": column.kind,
            "is_final": column.is_final,
            "is_default_name": is_default_column_name(
                board=board_code, code=column.code, name=column.name
            ),
            "is_custom": column.is_custom,
            "is_talked": column.is_talked,
            "may_talk": column.code in markable,
        }

    return {
        "board": board_code,
        "live_since": selectors.live_since(db, board=staff.board),
        "columns": [
            out(column)
            for column in selectors.columns_for(
                db, board=staff.board, access=staff.access
            )
        ],
        "removed": [
            out(column) for column in selectors.removed_columns(db, board=staff.board)
        ],
        "may_edit": bool(staff.user.is_superuser),
        "max_columns": COLUMNS_MAX,
    }


@router.get("/boards/{board}", responses={200: {"model": BoardViewOut}})
def board(
    db: Db,
    staff: BoardStaff,
    column: Annotated[
        str, Query(max_length=24, description="One column only, for its next page.")
    ] = "",
    q: Annotated[str, Query(max_length=100, description="Name, email or phone.")] = "",
    mine: Annotated[bool, Query(description="Only the reader's own cards.")] = False,
    manager: Annotated[
        str,
        Query(max_length=36, description="A staff member's id, or `none`: nobody's."),
    ] = "",
    due: Annotated[
        str,
        Query(
            max_length=8,
            description="`overdue`: the deadline passed; `today`: due on the "
            "office's day today; `set`: any deadline.",
        ),
    ] = "",
    reason: Annotated[
        str,
        Query(
            max_length=24,
            description="Support: a ticket reason's code. Uzaytirish: a "
            "decline reason's code.",
        ),
    ] = "",
    plan: Annotated[
        str, Query(max_length=32, description="Uzaytirish: `standart` or `pro`.")
    ] = "",
    term_from: Annotated[
        date | None,
        Query(description="Uzaytirish: the term ends on this office day or later."),
    ] = None,
    term_to: Annotated[
        date | None,
        Query(description="Uzaytirish: the term ends on this office day or earlier."),
    ] = None,
    attempts: Annotated[
        str,
        Query(
            max_length=3,
            description="Sotuv and Uzaytirish: «Bog'lanib bo'lmadi» presses: "
            "`0`, `1-2` or `3+`.",
        ),
    ] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=COLUMN_CARDS_MAX)] = COLUMN_CARDS,
) -> dict[str, Any]:
    """The board as this person sees it: a sales manager and a Support
    member only their own cards, the board's lead (on Support: the superuser
    and the Owner) everything. In a column the nearest deadline is on top."""
    now = utcnow()
    selectors.ensure_board(db, board=staff.board, now=now)
    db.commit()
    return view.board_view(
        db,
        board=staff.board,
        user=staff.user,
        access=staff.access,
        now=now,
        column=column,
        search=q,
        filters=view.Filters(
            mine=mine,
            manager=manager,
            due=due,
            reason=reason,
            plan=plan,
            term_from=term_from,
            term_to=term_to,
            attempts=attempts,
        ),
        offset=offset,
        limit=limit,
    )


@router.get("/boards/{board}/staff", responses={200: {"model": StaffListOut}})
def board_people(db: Db, staff: BoardStaff) -> dict[str, Any]:
    """Who a card on this board can be given to. For the board's lead."""
    if not staff.access.leads_board(staff.board):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return {"staff": view.board_staff(db, board=staff.board)}


@router.get("/boards/{board}/clients", responses={200: {"model": ClientsFoundOut}})
def board_clients(
    db: Db, staff: BoardStaff, q: Annotated[str, Query(min_length=3, max_length=100)]
) -> dict[str, Any]:
    """Signed-up clients to open a card for, by email, phone or name. For
    who may add a card to this board."""
    _may_add(staff)
    return {"clients": view.search_clients(db, board=staff.board, q=q)}


def _may_add(staff: BoardStaff) -> None:
    # A renewal card is opened by the term running out, never by hand.
    allowed = (
        staff.access.leads_board(Board.SALES)
        if staff.board == Board.SALES
        else staff.board == Board.SUPPORT and staff.access.sees(Board.SUPPORT)
    )
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.post(
    "/boards/{board}/cards",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": CardDetailOut}},
)
def add_card(db: Db, staff: BoardStaff, body: CardAddIn) -> dict[str, Any]:
    """A card opened by hand. Sales (the lead, the Owner, the superuser): a
    client who has not paid becomes a lead, in Ishlanmagan or with
    `staff_id`. Support: the client's ticket opens, or takes one more
    reason; `note` says why. The Owner and the superuser may send it to a
    Support member with `staff_id`; a Support member's own goes to
    themselves, into Ishlanmoqda, while they have room under the limit."""
    _may_add(staff)
    now = utcnow()
    try:
        client_id = uuid.UUID(body.user_id)
        to_id = uuid.UUID(body.staff_id) if body.staff_id else None
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Mijoz topilmadi."
        ) from None
    if staff.board == Board.SALES:
        found = services.add_lead(
            db,
            client_id=client_id,
            user=staff.user,
            access=staff.access,
            note=body.note,
            to_id=to_id,
            now=now,
        )
    else:
        found = services.add_ticket(
            db,
            client_id=client_id,
            user=staff.user,
            access=staff.access,
            note=body.note,
            to_id=to_id,
            now=now,
        )
    return view.card_detail(db, card=found, now=now)


@router.get("/boards/{board}/reasons", responses={200: {"model": list[ReasonOut]}})
def board_reasons(
    db: Db,
    staff: BoardStaff,
    purpose: Annotated[
        str,
        Query(
            description="`close` (Sotuv), `decline` (Uzaytirish), `no_contact`, "
            "`move`. Empty: the board's main list (`close`, `decline`; `move` on Support)."
        ),
    ] = "",
) -> list[dict[str, Any]]:
    """The reasons to pick from, in order: why a Sales card is closed, why
    a client does not renew, why a call did not reach them, why a card is
    moved by hand. An empty `no_contact` or `move` list is not asked."""
    chosen = reason_lists.checked_purpose(
        staff.board, purpose or str(BOARD_MAIN_PURPOSE[staff.board])
    )
    reason_lists.ensure(db, now=utcnow())
    db.commit()
    return [
        {"value": row.code, "label": row.name, "note_required": row.note_required}
        for row in reason_lists.rows(db, board=staff.board, purpose=chosen)
    ]


@router.get("/boards/{board}/reason-lists", responses={200: {"model": ReasonListsOut}})
def reason_lists_view(db: Db, staff: BoardStaff) -> dict[str, Any]:
    """Every list of reasons the board has, for its settings."""
    reason_lists.ensure(db, now=utcnow())
    db.commit()
    return reason_lists.lists_view(
        db, board=staff.board, may_edit=bool(staff.user.is_superuser)
    )


@router.post(
    "/boards/{board}/reason-lists/{purpose}",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": ReasonRowOut}},
)
@_journaled(SettingArea.REASON)
def add_reason(
    db: Db, staff: BoardStaff, purpose: str, body: ReasonAddIn
) -> dict[str, Any]:
    """A new reason at the end of the list. For the superuser."""
    _columns_keeper(staff)
    row = reason_lists.add(
        db,
        board=staff.board,
        purpose=reason_lists.checked_purpose(staff.board, purpose),
        name=body.name,
        note_required=body.note_required,
        actor_id=staff.user.id,
        now=utcnow(),
    )
    logger.info(
        "board reason added",
        extra={
            "board": str(staff.board),
            "purpose": purpose,
            "code": row.code,
            "actor_id": str(staff.user.id),
        },
    )
    return reason_lists.row_out(row)


@router.put(
    "/boards/{board}/reason-lists/{purpose}/{reason_id}",
    responses={200: {"model": ReasonRowOut}},
)
@_journaled(SettingArea.REASON)
def edit_reason(
    db: Db, staff: BoardStaff, purpose: str, reason_id: uuid.UUID, body: ReasonEditIn
) -> dict[str, Any]:
    """New words, place, or whether a line is asked; cards that carry the
    reason read the new words. For the superuser."""
    _columns_keeper(staff)
    return reason_lists.row_out(
        reason_lists.edit(
            db,
            board=staff.board,
            purpose=reason_lists.checked_purpose(staff.board, purpose),
            reason_id=reason_id,
            name=body.name,
            position=body.position,
            note_required=body.note_required,
            now=utcnow(),
        )
    )


@router.post(
    "/boards/{board}/reason-lists/{purpose}/{reason_id}/archive",
    responses={200: {"model": ReasonRowOut}},
)
@_journaled(SettingArea.REASON)
def archive_reason(
    db: Db, staff: BoardStaff, purpose: str, reason_id: uuid.UUID
) -> dict[str, Any]:
    """Off the list to pick from; cards and reports keep it."""
    _columns_keeper(staff)
    return reason_lists.row_out(
        reason_lists.set_archived(
            db,
            board=staff.board,
            purpose=reason_lists.checked_purpose(staff.board, purpose),
            reason_id=reason_id,
            archived=True,
            now=utcnow(),
        )
    )


@router.post(
    "/boards/{board}/reason-lists/{purpose}/{reason_id}/restore",
    responses={200: {"model": ReasonRowOut}},
)
@_journaled(SettingArea.REASON)
def restore_reason(
    db: Db, staff: BoardStaff, purpose: str, reason_id: uuid.UUID
) -> dict[str, Any]:
    _columns_keeper(staff)
    return reason_lists.row_out(
        reason_lists.set_archived(
            db,
            board=staff.board,
            purpose=reason_lists.checked_purpose(staff.board, purpose),
            reason_id=reason_id,
            archived=False,
            now=utcnow(),
        )
    )


@router.get("/boards/sales/report", responses={200: {"model": SalesReportOut}})
def sales_report(
    db: Db,
    user: Staff,
    date_from: Annotated[
        date | None, Query(description="The first office day; 30 days back if empty.")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="The last office day; today if empty.")
    ] = None,
) -> dict[str, Any]:
    """The Sales board's period: the totals, each day, and each staff member
    (taken, called, sold, money, closed and why, calls, first-touch speed,
    cards in hand now), plus the leads by how they signed up. A manager reads
    their own figures; the Sales lead, the Owner and the superuser everybody's."""
    access = access_for(db, user)
    if not access.sees(Board.SALES):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    end = date_to or localtime(utcnow()).date()
    start = date_from or end - timedelta(days=REPORT_DEFAULT_DAYS - 1)
    return sales_report_module.report(
        db, user=user, access=access, start=start, end=end
    )


def _contact_reader(db: Db, user: Staff) -> Any:
    access = access_for(db, user)
    if not access.sees(Board.SUPPORT):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return access


def _contact_keeper(db: Db, user: Staff) -> None:
    """The superuser keeps the list, as every list of reasons."""
    _contact_reader(db, user)
    if not user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Ruxsat yo'q.")


def _contact_out(row: ContactReason) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "position": row.position,
        "is_archived": row.is_archived,
    }


def _contact_row(db: Db, reason_id: uuid.UUID) -> ContactReason:
    found = db.get(ContactReason, reason_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return found


@router.get(
    "/boards/support/contact-reasons", responses={200: {"model": ContactReasonsOut}}
)
def contact_reasons(db: Db, user: Staff) -> dict[str, Any]:
    """Why Support cannot reach a client: what «Bog'lanib bo'lmadi» asks
    for. Archived ones only for who keeps the list."""
    full = _contact_reader(db, user).full
    keeps = bool(user.is_superuser)
    query = select(ContactReason).order_by(
        ContactReason.position, ContactReason.created_at
    )
    if not full:
        query = query.where(ContactReason.is_archived.is_(False))
    return {"rows": [_contact_out(row) for row in db.scalars(query)], "may_edit": keeps}


@router.post(
    "/boards/support/contact-reasons",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": ContactReasonOut}},
)
@_journaled(SettingArea.REASON)
def add_contact_reason(body: ContactReasonIn, db: Db, user: Staff) -> dict[str, Any]:
    _contact_keeper(db, user)
    position = (
        body.position
        or int(
            db.scalar(select(func.coalesce(func.max(ContactReason.position), 0))) or 0
        )
        + 1
    )
    row = ContactReason(
        name=body.name.strip(), position=position, created_by_id=user.id
    )
    db.add(row)
    db.commit()
    return _contact_out(row)


@router.put(
    "/boards/support/contact-reasons/{reason_id}",
    responses={200: {"model": ContactReasonOut}},
)
@_journaled(SettingArea.REASON)
def edit_contact_reason(
    reason_id: uuid.UUID, body: ContactReasonIn, db: Db, user: Staff
) -> dict[str, Any]:
    """New words or place; tickets standing there read the new words."""
    _contact_keeper(db, user)
    row = _contact_row(db, reason_id)
    row.name = body.name.strip()
    row.position = body.position
    db.commit()
    return _contact_out(row)


@router.post(
    "/boards/support/contact-reasons/{reason_id}/archive",
    responses={200: {"model": ContactReasonOut}},
)
@_journaled(SettingArea.REASON)
def archive_contact_reason(reason_id: uuid.UUID, db: Db, user: Staff) -> dict[str, Any]:
    """Off the list to pick from; tickets that have it keep it."""
    _contact_keeper(db, user)
    row = _contact_row(db, reason_id)
    row.is_archived = True
    db.commit()
    return _contact_out(row)


@router.post(
    "/boards/support/contact-reasons/{reason_id}/restore",
    responses={200: {"model": ContactReasonOut}},
)
@_journaled(SettingArea.REASON)
def restore_contact_reason(reason_id: uuid.UUID, db: Db, user: Staff) -> dict[str, Any]:
    _contact_keeper(db, user)
    row = _contact_row(db, reason_id)
    row.is_archived = False
    db.commit()
    return _contact_out(row)


def _renewal(db: Db, user: Staff) -> Any:
    access = access_for(db, user)
    if not access.sees(Board.RENEWAL):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return access


@router.get("/boards/renewal/report", responses={200: {"model": RenewalReportOut}})
def renewal_report(
    db: Db,
    user: Staff,
    date_from: Annotated[
        date | None, Query(description="The first office day; 30 days back if empty.")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="The last office day; today if empty.")
    ] = None,
) -> dict[str, Any]:
    """The terms that came due in the period, Standart and Pro apart: how
    many, how many renewed and the share, the money, and why the rest
    declined. A renewal manager's report counts their own cards; the Sales
    lead, the Owner and the superuser read everybody's."""
    access = _renewal(db, user)
    end = date_to or localtime(utcnow()).date()
    start = date_from or end - timedelta(days=REPORT_DEFAULT_DAYS - 1)
    return renewal.report(db, user=user, access=access, start=start, end=end)


@router.get("/boards/renewal/manager", responses={200: {"model": RenewalManagerOut}})
def renewal_manager(db: Db, user: Staff) -> dict[str, Any]:
    """Who every new renewal card goes to. For the superuser and the Owner."""
    _full(db, user)
    return {**renewal.manager_view(db), "moved": 0}


@router.put("/boards/renewal/manager", responses={200: {"model": RenewalManagerOut}})
def set_renewal_manager(db: Db, user: Staff, body: RenewalManagerIn) -> dict[str, Any]:
    """Pick the renewal board's manager. The cards still worked pass to the
    new one at once. For the superuser and the Owner."""
    _full(db, user)
    try:
        to_id = uuid.UUID(body.staff_id) if body.staff_id else None
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Xodim topilmadi."
        ) from None
    moved = renewal.set_manager(db, to_id=to_id, actor=user, now=utcnow())
    return {**renewal.manager_view(db), "moved": moved}


@router.get("/boards/support/report", responses={200: {"model": SupportReportOut}})
def support_daily_report(
    db: Db,
    user: Staff,
    date_from: Annotated[
        date | None, Query(description="The first office day; today if empty.")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="The last office day; today if empty.")
    ] = None,
) -> dict[str, Any]:
    """Each member of Support by day: clients talked to, tickets taken and
    called solved, and the clients' answers. A member reads their own; the
    Owner and the superuser read everybody's."""
    access = access_for(db, user)
    if not access.sees(Board.SUPPORT):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    end = date_to or localtime(utcnow()).date()
    start = date_from or end
    return support_report.report(db, user=user, access=access, start=start, end=end)


@router.get("/boards/support/kinds", responses={200: {"model": SupportKindsOut}})
def support_kinds(db: Db, user: Staff) -> dict[str, Any]:
    """Which kinds of ticket each member of Support takes first. For the
    superuser and the Owner."""
    _full(db, user)
    return kinds.kinds_view(db)


@router.put(
    "/boards/support/kinds/{member_id}",
    responses={200: {"model": SupportMemberKindsOut}},
)
def set_support_kinds(
    db: Db, user: Staff, member_id: str, body: SupportKindsIn
) -> dict[str, Any]:
    """Set the kinds a member of Support takes first. «Zayavka olish» gives
    them those, and the oldest of any kind once none of those waits. For the
    superuser and the Owner."""
    _full(db, user)
    member = _card_id(member_id)
    kinds.set_kinds(db, member_id=member, kinds=body.kinds, actor=user)
    db.commit()
    return kinds.member_view(db, member_id=member)


@router.get("/boards/sales/kinds", responses={200: {"model": SalesKindsOut}})
def sales_kinds_list(db: Db, user: Staff) -> dict[str, Any]:
    """Which kinds of lead each Sales manager takes first. For the superuser
    and the Owner."""
    _full(db, user)
    return sales_kinds.kinds_view(db)


@router.put(
    "/boards/sales/kinds/{member_id}",
    responses={200: {"model": SupportMemberKindsOut}},
)
def set_sales_kinds(
    db: Db, user: Staff, member_id: str, body: SalesKindsIn
) -> dict[str, Any]:
    """Set the kinds of lead a Sales manager takes first. «Lid olish» gives
    them those, and any kind once none of those waits. For the superuser and
    the Owner."""
    _full(db, user)
    member = _card_id(member_id)
    sales_kinds.set_kinds(db, member_id=member, kinds=body.kinds, actor=user)
    db.commit()
    return sales_kinds.member_view(db, member_id=member)


@router.post("/sales/take-by-phone", responses={200: {"model": CardDetailOut}})
def take_by_phone(db: Db, user: Staff, body: PhoneTakeIn) -> dict[str, Any]:
    """Take a lead by the client's number, whatever its kind or place in the
    queue and over the «Lid olish» limit: a lead nobody works becomes this
    manager's, in Yangi lead. A client who paid a full plan before anybody
    took them may be claimed for 12 hours after paying; the sale is then
    this manager's. 404 `no_such_lead` («Bunday lid yo'q»): no such client,
    or a full plan bought longer ago; 409 `lead_with_other` («Bu lid boshqa
    menejerda») and `lead_is_yours` («Bu lid sizda»)."""
    if not may_take(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    now = utcnow()
    card = phone_take.take_by_phone(db, manager=user, phone=body.phone, now=now)
    return view.card_detail(db, card=card, now=now)


@router.post("/sales/take", responses={200: {"model": CardDetailOut}})
def take(db: Db, user: Staff) -> dict[str, Any]:
    """«Lid olish»: the next lead in Ishlanmagan nobody works becomes this
    manager's, in Yangi lead: their own kinds first, Start buyers before new
    sign-ups (``services.take_lead``)."""
    if not may_take(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    now = utcnow()
    card = services.take_lead(db, manager=user, now=now)
    return view.card_detail(db, card=card, now=now)


@router.post("/support/take", responses={200: {"model": CardDetailOut}})
def take_ticket(db: Db, user: Staff) -> dict[str, Any]:
    """«Zayavka olish»: the ticket that waited longest with nobody on it
    becomes this person's, in Ishlanmoqda. One a press; 409 while they have
    the limit there, or when the queue is empty."""
    if not may_take_ticket(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    now = utcnow()
    card = services.take_ticket(db, member=user, now=now)
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


@router.get("/cards/{card_id}/client", responses={200: {"model": CardClientOut}})
def card_client(db: Db, user: Staff, card_id: str) -> dict[str, Any]:
    """The card's client in short, to read only: profile, business, term,
    Meta, pages and the newest bills. Whoever sees the card may read it;
    the reading is written to the journal."""
    found = services.card_for(
        db, card_id=_card_id(card_id), user=user, access=access_for(db, user)
    )
    owner = db.get(User, found.owner_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    seen(db, customer=owner, actor=user)
    db.commit()
    return client.brief(db, owner=owner, now=localtime(utcnow()))


@router.post("/cards/{card_id}/actions", responses={200: {"model": CardDetailOut}})
def press(db: Db, user: Staff, card_id: str, body: ActionIn) -> dict[str, Any]:
    """A button on the card. Only the buttons in its `actions` are accepted."""
    now = utcnow()
    found = services.act(
        db,
        card_id=_card_id(card_id),
        user=user,
        access=access_for(db, user),
        code=body.action,
        now=now,
        on=body.on,
        reason=body.reason,
        note=body.note,
        due_at=body.due_at,
    )
    return view.card_detail(db, card=found, now=now)


@router.put("/cards/{card_id}/due", responses={200: {"model": CardDetailOut}})
def due(db: Db, user: Staff, card_id: str, body: DueIn) -> dict[str, Any]:
    """The card's deadline: set, moved or taken off (`due_at: null`) by who
    works it. The card stays in its column."""
    now = utcnow()
    found = services.set_due(
        db,
        card_id=_card_id(card_id),
        user=user,
        access=access_for(db, user),
        due_at=body.due_at,
        note=body.note,
        now=now,
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


@router.get("/boards/{board}/buttons", responses={200: {"model": ButtonsOut}})
def board_buttons(db: Db, staff: BoardStaff) -> dict[str, Any]:
    """Every column of the board with the buttons its cards show, the
    buttons a column may be given and the columns a button may send a card
    to. Read by whoever opens the board's settings."""
    selectors.ensure_board(db, board=staff.board, now=utcnow())
    out = buttons.settings_view(
        db, board=staff.board, may_edit=bool(staff.user.is_superuser)
    )
    db.commit()
    return out


@router.post(
    "/boards/{board}/buttons",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": ButtonsOut}},
)
@_journaled(SettingArea.BUTTON)
def add_button(db: Db, staff: BoardStaff, body: ButtonAddIn) -> dict[str, Any]:
    """One more button on a column: one of the code's it lacks, or one of
    the superuser's own (`go`) with its words and its column."""
    _columns_keeper(staff)
    row = buttons.add(
        db,
        board=staff.board,
        column_code=body.column,
        action=body.action,
        label=body.label,
        to_column=body.to_column,
        due=body.due,
        note_required=body.note_required,
        actor_id=staff.user.id,
        now=utcnow(),
    )
    logger.info(
        "board button added",
        extra={
            "board": str(staff.board),
            "column": body.column,
            "code": row.code,
            "actor_id": str(staff.user.id),
        },
    )
    return board_buttons(db, staff)


@router.post("/boards/{board}/buttons/reset", responses={200: {"model": ButtonsOut}})
@_journaled(SettingArea.BUTTON)
def reset_buttons(db: Db, staff: BoardStaff, body: ButtonResetIn) -> dict[str, Any]:
    """The column's buttons as the code gives them («Standartga qaytarish»)."""
    _columns_keeper(staff)
    buttons.reset(db, board=staff.board, column_code=body.column, now=utcnow())
    logger.info(
        "board buttons reset",
        extra={
            "board": str(staff.board),
            "column": body.column,
            "actor_id": str(staff.user.id),
        },
    )
    return board_buttons(db, staff)


@router.put(
    "/boards/{board}/buttons/{button_id}", responses={200: {"model": ButtonsOut}}
)
@_journaled(SettingArea.BUTTON)
def edit_button(
    db: Db, staff: BoardStaff, button_id: uuid.UUID, body: ButtonEditIn
) -> dict[str, Any]:
    """A button's words, column and place; one of the superuser's own also
    what it asks for."""
    _columns_keeper(staff)
    buttons.edit(
        db,
        board=staff.board,
        button_id=button_id,
        label=body.label,
        to_column=body.to_column,
        due=body.due,
        note_required=body.note_required,
        position=body.position,
        now=utcnow(),
    )
    return board_buttons(db, staff)


@router.delete(
    "/boards/{board}/buttons/{button_id}", responses={200: {"model": ButtonsOut}}
)
@_journaled(SettingArea.BUTTON)
def remove_button(db: Db, staff: BoardStaff, button_id: uuid.UUID) -> dict[str, Any]:
    """The button off its column."""
    _columns_keeper(staff)
    column = buttons.remove(db, board=staff.board, button_id=button_id)
    logger.info(
        "board button removed",
        extra={
            "board": str(staff.board),
            "column": column,
            "actor_id": str(staff.user.id),
        },
    )
    return board_buttons(db, staff)


@router.get("/boards/{board}/rules", responses={200: {"model": RulesOut}})
def board_rules(db: Db, staff: BoardStaff) -> dict[str, Any]:
    """Every automatic rule of the board in plain words: the system's with
    what may be changed of each, then the superuser's own. Read by whoever
    opens the board's settings."""
    selectors.ensure_board(db, board=staff.board, now=utcnow())
    out = rules.settings_view(
        db, board=staff.board, may_edit=bool(staff.user.is_superuser)
    )
    db.commit()
    return out


@router.post(
    "/boards/{board}/rules",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": RulesOut}},
)
@_journaled(SettingArea.RULE)
def add_rule(db: Db, staff: BoardStaff, body: RuleAddIn) -> dict[str, Any]:
    """A rule of the superuser's own: a card that stood in a column long
    enough (`stay`), or whose own time passed (`due`), goes to another."""
    _columns_keeper(staff)
    row = rules.add_custom(
        db,
        board=staff.board,
        actor_id=staff.user.id,
        now=utcnow(),
        kind=body.kind,
        name=body.name,
        from_columns=body.from_columns,
        to_column=body.to_column,
        amount=body.amount,
        unit=body.unit,
        reason=body.reason,
        **_rule_extras(body.model_dump()),
    )
    logger.info(
        "board rule added",
        extra={
            "board": str(staff.board),
            "code": row.code,
            "actor_id": str(staff.user.id),
        },
    )
    return board_rules(db, staff)


_RULE_EXTRAS = (
    "attempts_min",
    "plans",
    "bill",
    "due_amount",
    "due_unit",
    "notify_manager",
    "notify_lead",
    "notify_text",
    "assign_to",
)


def _rule_extras(sent: dict[str, Any]) -> dict[str, Any]:
    """A rule's conditions and what it does besides moving, as sent."""
    return {key: sent[key] for key in _RULE_EXTRAS}


@router.post(
    "/boards/{board}/rules/preview", responses={200: {"model": RulePreviewOut}}
)
def preview_rule(db: Db, staff: BoardStaff, body: RulePreviewIn) -> dict[str, Any]:
    """Try a rule before keeping it: how many cards it would act on this
    minute, and the first of them. Nothing is changed. For the superuser."""
    _columns_keeper(staff)
    code = ""
    if body.rule_id:
        try:
            code = rules.code_of(db, board=staff.board, rule_id=uuid.UUID(body.rule_id))
        except ValueError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND) from error
    return rules.preview(
        db,
        board=staff.board,
        now=utcnow(),
        code=code,
        kind=body.kind,
        name=body.name,
        from_columns=body.from_columns,
        to_column=body.to_column,
        amount=body.amount,
        unit=body.unit,
        reason=body.reason,
        **_rule_extras(body.model_dump()),
    )


@router.patch("/boards/{board}/rules/{rule_id}", responses={200: {"model": RulesOut}})
@_journaled(SettingArea.RULE)
def edit_rule(
    db: Db, staff: BoardStaff, rule_id: uuid.UUID, body: RuleEditIn
) -> dict[str, Any]:
    """Change a rule: of the system's, the fields its `editable` names; of
    the superuser's own, everything (send it whole)."""
    _columns_keeper(staff)
    sent = body.model_dump(exclude_unset=True)
    now = utcnow()
    if rules.is_custom(db, board=staff.board, rule_id=rule_id):
        rules.edit_custom(
            db,
            board=staff.board,
            rule_id=rule_id,
            actor_id=staff.user.id,
            now=now,
            is_enabled=bool(sent.get("is_enabled", True)),
            kind=str(sent.get("kind", "")),
            name=str(sent.get("name", "")),
            from_columns=list(sent.get("from_columns") or []),
            to_column=str(sent.get("to_column", "")),
            amount=int(sent.get("amount") or 0),
            unit=str(sent.get("unit", "")),
            reason=str(sent.get("reason", "")),
            **_rule_extras(body.model_dump()),
        )
    else:
        rules.edit_system(
            db,
            board=staff.board,
            rule_id=rule_id,
            changes={
                key: value
                for key, value in sent.items()
                if key
                in ("is_enabled", "from_columns", "to_column", "amount", "reason")
                and value is not None
            },
            actor_id=staff.user.id,
            now=now,
        )
    logger.info(
        "board rule changed",
        extra={
            "board": str(staff.board),
            "rule_id": str(rule_id),
            "fields": sorted(sent),
            "actor_id": str(staff.user.id),
        },
    )
    return board_rules(db, staff)


@router.post(
    "/boards/{board}/rules/{rule_id}/reset", responses={200: {"model": RulesOut}}
)
@_journaled(SettingArea.RULE)
def reset_rule(db: Db, staff: BoardStaff, rule_id: uuid.UUID) -> dict[str, Any]:
    """A rule of the system's as the code has it («Standartga qaytarish»)."""
    _columns_keeper(staff)
    rules.reset_system(
        db, board=staff.board, rule_id=rule_id, actor_id=staff.user.id, now=utcnow()
    )
    return board_rules(db, staff)


@router.delete("/boards/{board}/rules/{rule_id}", responses={200: {"model": RulesOut}})
@_journaled(SettingArea.RULE)
def remove_rule(db: Db, staff: BoardStaff, rule_id: uuid.UUID) -> dict[str, Any]:
    """One of the superuser's own rules, gone. The system's are switched
    off, never removed."""
    _columns_keeper(staff)
    rules.remove_custom(db, board=staff.board, rule_id=rule_id)
    return board_rules(db, staff)


@router.get(
    "/boards/{board}/columns/report", responses={200: {"model": ColumnsReportOut}}
)
def columns_report_view(
    db: Db,
    staff: BoardStaff,
    date_from: Annotated[
        date | None, Query(description="The first office day; 30 days back if empty.")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="The last office day; today if empty.")
    ] = None,
) -> dict[str, Any]:
    """The board column by column over a period: cards standing in each
    now, cards that came into it, and how long a card stood there before
    leaving. Columns the superuser added are on it like the rest. A manager
    reads their own cards; the lead, the Owner and the superuser everybody's."""
    end = date_to or localtime(utcnow()).date()
    start = date_from or end - timedelta(days=REPORT_DEFAULT_DAYS - 1)
    return columns_report.report(
        db,
        board=staff.board,
        user=staff.user,
        access=staff.access,
        start=start,
        end=end,
    )


@router.get(
    "/boards/{board}/settings/history", responses={200: {"model": SettingsHistoryOut}}
)
def settings_history(
    db: Db,
    staff: BoardStaff,
    area: Annotated[
        str, Query(max_length=16, description="One of `areas`; empty: all.")
    ] = "",
    before: Annotated[
        datetime | None, Query(description="`next_before` of the last page.")
    ] = None,
) -> dict[str, Any]:
    """Who changed the board's settings and what: every column, reason,
    button and rule added, changed or taken off, newest first. For the
    superuser and the Owner."""
    if not staff.access.full:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return settings_log.history(db, board=staff.board, area=area, before=before)


def _columns_keeper(staff: BoardStaff) -> None:
    """Only the superuser changes a board's columns; the Owner reads them."""
    if staff.user.is_superuser:
        return
    if staff.access.full:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Ruxsat yo'q.")
    raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.post(
    "/boards/{board}/columns",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": ColumnsOut}},
)
@_journaled(SettingArea.COLUMN)
def add_column(db: Db, staff: BoardStaff, body: ColumnAddIn) -> dict[str, Any]:
    """A new column of the superuser's own. Cards reach it and leave it
    only by `POST /cards/{id}/move`; no rule and no button knows it, and it
    never closes a card. The board's columns, the new one among them."""
    _columns_keeper(staff)
    now = utcnow()
    selectors.ensure_board(db, board=staff.board, now=now)
    code = selectors.add_column(
        db,
        board=staff.board,
        name=body.name,
        after=body.after or None,
        actor_id=staff.user.id,
        now=now,
    )
    logger.info(
        "board column added",
        extra={"board": str(staff.board), "code": code, "actor_id": str(staff.user.id)},
    )
    return columns(db, staff)


@router.get(
    "/boards/{board}/columns/{code}/removal",
    responses={200: {"model": ColumnRemovalOut}},
)
def column_removal(db: Db, staff: BoardStaff, code: str) -> dict[str, Any]:
    """What taking this column off the board touches, to ask before it:
    the cards standing in it and the columns they may go to, the buttons
    that send cards to it and the rules that use it. For the superuser."""
    _columns_keeper(staff)
    return selectors.removal_view(db, board=staff.board, code=code)


@router.delete("/boards/{board}/columns/{code}", responses={200: {"model": ColumnsOut}})
@_journaled(SettingArea.RULE)
@_journaled(SettingArea.BUTTON)
@_journaled(SettingArea.COLUMN)
def remove_column(
    db: Db,
    staff: BoardStaff,
    code: str,
    move_to: Annotated[
        str,
        Query(
            max_length=24,
            description="Where the column's cards go; needed while it has any "
            "(one of `targets` of `GET …/removal`).",
        ),
    ] = "",
) -> dict[str, Any]:
    """Take one of the superuser's own columns off the board. Its cards go
    to `move_to` first, each with a line in its history; without it a column
    with cards is refused (422 `column_has_cards`). Buttons and rules that
    used the column are let go of it: a button of the superuser's own that
    sent cards there is removed, a rule of their own is switched off, and
    the system's go back to their own columns. Refused for the columns the
    board came with."""
    _columns_keeper(staff)
    moved = selectors.remove_column(
        db,
        board=staff.board,
        code=code,
        actor=staff.user,
        now=utcnow(),
        move_to=move_to,
    )
    logger.info(
        "board column removed",
        extra={
            "board": str(staff.board),
            "code": code,
            "moved": moved,
            "actor_id": str(staff.user.id),
        },
    )
    return columns(db, staff)


@router.post(
    "/boards/{board}/columns/{code}/restore", responses={200: {"model": ColumnsOut}}
)
@_journaled(SettingArea.COLUMN)
def restore_column(db: Db, staff: BoardStaff, code: str) -> dict[str, Any]:
    """Put a removed column back, before the final columns."""
    _columns_keeper(staff)
    selectors.restore_column(
        db, board=staff.board, code=code, actor_id=staff.user.id, now=utcnow()
    )
    return columns(db, staff)


@router.put(
    "/boards/{board}/columns/{code}/talked", responses={200: {"model": ColumnsOut}}
)
@_journaled(SettingArea.COLUMN)
def mark_column_talked(
    db: Db, staff: BoardStaff, code: str, body: ColumnTalkedIn
) -> dict[str, Any]:
    """Sales: whether a card standing in this column counts as talked to.
    A client who buys Start while their card stands in such a column gets
    the discount at once; elsewhere the card waits for «Gaplashildi». For
    the superuser; `may_talk` names the columns it may be set on."""
    _columns_keeper(staff)
    selectors.mark_talked(
        db,
        board=staff.board,
        code=code,
        talked=body.talked,
        actor_id=staff.user.id,
        now=utcnow(),
    )
    return columns(db, staff)


@router.patch("/boards/{board}/columns", responses={200: {"model": ColumnsOut}})
@_journaled(SettingArea.COLUMN)
def edit_columns(db: Db, staff: BoardStaff, body: ColumnsIn) -> dict[str, Any]:
    """Rename and reorder the board's columns. For the superuser. Send
    every visible column, in the order wanted."""
    _columns_keeper(staff)
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
        reason_code=body.reason_code,
        contact_reason=body.contact_reason,
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
