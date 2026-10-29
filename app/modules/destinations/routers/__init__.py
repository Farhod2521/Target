"""The spreadsheet button on the customers screen, and Google's round trip."""

import uuid
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.cache import cache
from app.common.config import settings
from app.common.exceptions import DomainError, InputRefused
from app.common.i18n import get_language
from app.modules.accounts.models import User
from app.modules.destinations import selectors, services
from app.modules.destinations.constants import (
    BROKEN_REASON_LABELS,
    BrokenReason,
    SheetMode,
    SheetStatus,
)
from app.modules.destinations.exceptions import (
    GoogleDeclined,
    GoogleStateMismatch,
    PickerExpired,
)
from app.modules.destinations.schemas import (
    ChoiceIn,
    ChooserOut,
    FormFileOut,
    FormLabelOut,
    ModeOut,
    PanelOut,
    PickerOut,
    PickIn,
    SheetPanelOut,
    StartOut,
)
from app.modules.destinations.services import SheetChoice

router = APIRouter(prefix="/destinations", tags=["destinations"])

# Where both halves of the handshake land: the screen the button is on.
LEADS: Final = "/app/leads"
STATE_TTL: Final = 15 * 60
POLL_SECONDS: Final = 3
DELAYED_POLL_SECONDS: Final = 30


def panel_out(db: Session, *, owner: User) -> SheetPanelOut:
    panel = selectors.sheet_panel(db, owner=owner)
    chooser = panel.chooser
    poll = None
    if panel.state == "preparing":
        poll = DELAYED_POLL_SECONDS if panel.delayed else POLL_SECONDS
    return SheetPanelOut(
        state=panel.state,
        mode=panel.mode,
        url=panel.url,
        email=panel.email,
        reason=panel.reason,
        reason_label=BROKEN_REASON_LABELS[BrokenReason(panel.reason)]
        if panel.reason in BrokenReason.values
        else "",
        needs_new_sheet=panel.needs_new_sheet,
        needs_other_file=panel.needs_other_file,
        delayed=panel.delayed,
        poll_seconds=poll,
        since=panel.since,
        written=panel.written,
        files=[FormFileOut(name=f.name, url=f.url) for f in panel.files],
        only_form_name=panel.only_form_name,
        only_form=panel.only_form,
        picker_ready=panel.picker_ready,
        chooser=None
        if chooser is None
        else ChooserOut(
            own_file=chooser.own_file,
            forms=[
                FormLabelOut(pk=f.pk, name=f.name, page_name=f.page_name)
                for f in chooser.forms
            ],
            mode=chooser.mode,
            only_form=chooser.only_form,
        ),
    )


def _choice(body: ChoiceIn) -> SheetChoice | None:
    """The choice posted, or ``None`` for the press that chooses nothing."""
    one = body.mode == SheetMode.OWN_FILE and body.scope == "one"
    if one and not body.only_form:
        raise InputRefused({"only_form": "Qaysi forma ekanini tanlang."})
    if not body.mode:
        return None
    return SheetChoice(
        mode=SheetMode(body.mode), only_form_id=body.only_form if one else ""
    )


def _redirect_uri() -> str:
    return services.callback_uri(settings.site_url)


def _leave_for_google(
    db: Session, *, user: User, choice: SheetChoice | None, next_url: str
) -> str:
    """Keep the state and the choice beside it, and hand back Google's URL."""
    url, state, checked = services.start_sheet_link(
        db, user=user, redirect_uri=_redirect_uri(), choice=choice
    )
    cache.set(
        f"oauth:sheets:{state}",
        {
            "user": str(user.id),
            "next": next_url,
            "choice": checked.as_session() if checked else None,
        },
        timeout=STATE_TTL,
    )
    return url


def _recall_state(db: Session, *, state: str) -> tuple[User, str, Any]:
    """The person and choice this callback belongs to - popped whatever happens."""
    found = cache.get(f"oauth:sheets:{state}") if state else None
    if not found:
        raise GoogleStateMismatch
    cache.delete(f"oauth:sheets:{state}")
    user = db.get(User, uuid.UUID(found["user"]))
    if user is None or not user.is_active:
        raise GoogleStateMismatch
    return user, str(found.get("next") or ""), found.get("choice")


def _back(next_url: str, **params: str) -> RedirectResponse:
    path = (
        next_url
        if next_url.startswith("/") and not next_url.startswith("//")
        else LEADS
    )
    # The frontend's next may carry a query of its own (?connected=meta).
    base, _, query = path.partition("?")
    merged = dict(parse_qsl(query)) | params
    if "error" in params:
        merged.pop("connected", None)
    return RedirectResponse(f"{settings.site_url}{base}?{urlencode(merged)}")


@router.get("/sheet", responses={200: {"model": PanelOut}})
def sheet_panel(db: Db, user: CurrentUser) -> dict[str, Any]:
    """The button, in whatever state the owner's link is in."""
    if not selectors.sheets_enabled():
        return {"enabled": False, "panel": None}
    return {"enabled": True, "panel": panel_out(db, owner=user)}


@router.post("/google/start", responses={200: {"model": StartOut}})
def google_start(body: ChoiceIn, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Leave for Google with the choice of where leads go; none mends a stopped link."""
    choice = _choice(body)
    return {"url": _leave_for_google(db, user=user, choice=choice, next_url=body.next)}


@router.get("/google/callback", include_in_schema=False)
def google_callback(
    db: Db, state: str = "", code: str = "", error: str = ""
) -> RedirectResponse:
    next_url = ""
    try:
        user, next_url, stored = _recall_state(db, state=state)
        if not code:
            raise GoogleDeclined
        link = services.connect_sheet(
            db,
            user=user,
            code=code,
            redirect_uri=_redirect_uri(),
            choice=services.choice_from_session(stored),
        )
    except DomainError as exc:
        return _back(next_url, error=exc.message)
    if link.status == SheetStatus.CHOOSING:
        message = "Google ulandi. Endi jadvalingizni tanlang."
    else:
        message = "Google ulandi. Jadval bir daqiqada tayyor bo'ladi."
    return _back(next_url, connected="sheet", sheet=link.status, message=message)


@router.post("/sheet/mode", responses={200: {"model": ModeOut}})
def sheet_mode(body: ChoiceIn, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Another way of writing for a working link.

    One file or a file per form changes here, with the permission held; a
    file of the owner's own, or no choice, goes through Google (``url``).
    """
    choice = _choice(body)
    if choice is None or choice.mode == SheetMode.OWN_FILE:
        url = _leave_for_google(db, user=user, choice=choice, next_url=body.next)
        return {"url": url, "detail": "", "panel": None}
    services.change_sheet_mode(db, user=user, choice=choice)
    return {
        "url": "",
        "detail": "Yozish usuli o'zgardi. Yangi mijozlar endi shu usulda yoziladi.",
        "panel": panel_out(db, owner=user),
    }


@router.get("/sheet/picker", responses={200: {"model": PickerOut}, 410: {}})
def sheet_picker(response: Response, user: CurrentUser) -> dict[str, Any]:
    """What Google's file picker needs. A live key to the owner's Drive: never cached."""
    response.headers["Cache-Control"] = "no-store"
    setup = selectors.picker_setup(owner=user)
    if setup is None:
        raise PickerExpired
    return {
        "token": setup.token,
        "key": setup.api_key,
        "app_id": setup.app_id,
        "locale": get_language() or "",
    }


@router.post("/sheet/pick", responses={200: {"model": SheetPanelOut}})
def sheet_pick(body: PickIn, db: Db, user: CurrentUser) -> SheetPanelOut:
    """The file the owner picked, posted by the picker's own callback."""
    services.choose_own_file(db, user=user, file_id=body.file_id)
    return panel_out(db, owner=user)


@router.post("/sheet/disconnect", responses={200: {"model": SheetPanelOut}})
def sheet_disconnect(db: Db, user: CurrentUser) -> SheetPanelOut:
    """Stop copying leads into the spreadsheet. The file itself stays."""
    services.disconnect_sheet(db, user=user)
    return panel_out(db, owner=user)


@router.post("/sheet/recreate", responses={200: {"model": SheetPanelOut}})
def sheet_recreate(db: Db, user: CurrentUser) -> SheetPanelOut:
    """Make a new spreadsheet after the old one was deleted or binned."""
    services.recreate_sheet(db, user=user)
    return panel_out(db, owner=user)
