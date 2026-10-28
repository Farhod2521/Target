"""What the spreadsheet button on the customers screen says."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.destinations.constants import (
    NEEDS_NEW_SHEET,
    NEEDS_OTHER_FILE,
    BrokenReason,
    SheetMode,
    SheetStatus,
)
from app.modules.destinations.models import SheetLink
from app.modules.destinations.selectors.deliveries import delivered_count
from app.modules.destinations.selectors.sheet_link import (
    form_sheets_for,
    picker_enabled,
    picker_ready,
    sheet_link_for,
)
from app.modules.leads.selectors import FormLabel, owner_forms

type PanelState = Literal["off", "choosing", "preparing", "active", "broken"]


@dataclass(frozen=True, slots=True)
class FormFile:
    """One per-form file. ``name`` is empty for the forms never recorded here."""

    name: str
    url: str


@dataclass(frozen=True, slots=True)
class Chooser:
    """The three ways of writing, as the choice before Google offers them."""

    own_file: bool
    forms: tuple[FormLabel, ...]
    mode: str
    only_form: str


@dataclass(frozen=True, slots=True)
class SheetPanel:
    """One button's state.

    ``off`` is both "never connected" and "disconnected". ``delayed`` is a
    file still being made after Google turned the last attempt away.
    """

    state: PanelState = "off"
    mode: str = SheetMode.SINGLE
    url: str = ""
    email: str = ""
    reason: str = ""
    needs_new_sheet: bool = False
    needs_other_file: bool = False
    delayed: bool = False
    since: datetime | None = None
    written: int = 0
    files: tuple[FormFile, ...] = ()
    only_form_name: str = ""
    only_form: str = ""
    picker_ready: bool = False
    chooser: Chooser | None = None


def sheet_panel(db: Session, *, owner: User) -> SheetPanel:
    """The button for this owner's link, in whatever state it is in."""
    link = sheet_link_for(db, owner=owner)
    if link is None or link.status == SheetStatus.DISCONNECTED:
        return SheetPanel(chooser=_chooser(db, owner=owner, link=link))
    if link.status == SheetStatus.CHOOSING:
        return SheetPanel(
            state="choosing",
            mode=link.mode,
            email=link.google_email,
            only_form=str(link.only_form_id or ""),
            picker_ready=picker_ready(owner=owner),
        )
    if link.status == SheetStatus.PREPARING:
        return SheetPanel(
            state="preparing",
            mode=link.mode,
            email=link.google_email,
            delayed=bool(link.last_error_code),
        )
    if link.status == SheetStatus.BROKEN:
        return _broken(link)
    return _active(db, owner=owner, link=link)


def _broken(link: SheetLink) -> SheetPanel:
    own = link.mode == SheetMode.OWN_FILE
    remade = link.broken_reason in NEEDS_NEW_SHEET and (
        not own or link.broken_reason == BrokenReason.TAB_GONE
    )
    return SheetPanel(
        state="broken",
        mode=link.mode,
        url=link.spreadsheet_url,
        email=link.google_email,
        reason=link.broken_reason,
        needs_new_sheet=remade,
        needs_other_file=own and link.broken_reason in NEEDS_OTHER_FILE,
        since=link.deliver_from,
        only_form=str(link.only_form_id or ""),
    )


def _active(db: Session, *, owner: User, link: SheetLink) -> SheetPanel:
    files: tuple[FormFile, ...] = ()
    if link.mode == SheetMode.PER_FORM:
        files = tuple(
            FormFile(
                name=sheet.form.name if sheet.form else "", url=sheet.spreadsheet_url
            )
            for sheet in form_sheets_for(db, link=link)
        )
    return SheetPanel(
        state="active",
        mode=link.mode,
        url=link.spreadsheet_url,
        email=link.google_email,
        since=link.deliver_from,
        written=delivered_count(db, link=link),
        files=files,
        only_form_name=link.only_form.name if link.only_form else "",
        chooser=_chooser(db, owner=owner, link=link),
    )


def _chooser(db: Session, *, owner: User, link: SheetLink | None) -> Chooser:
    """The choice, opened on what the link has now - or on one file."""
    own_file = picker_enabled()
    return Chooser(
        own_file=own_file,
        forms=owner_forms(db, owner=owner) if own_file else (),
        mode=link.mode if link is not None else SheetMode.SINGLE,
        only_form=str(link.only_form_id or "") if link is not None else "",
    )


__all__ = ["Chooser", "FormFile", "SheetPanel", "sheet_panel"]
