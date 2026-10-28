"""Copying leads into one file per form, each made when its form first needs it."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from googlekit import SheetsClient
from sqlalchemy.orm import Session

from app.modules.businesses.selectors import business_timezone
from app.modules.destinations.models import FormSheet, SheetLink
from app.modules.destinations.selectors import fixed_columns, form_sheets_for, word
from app.modules.destinations.services.file_state import add_form_sheet
from app.modules.destinations.services.write_rows import send_rows
from app.modules.leads.models import Lead

# A file list cuts long names; the form's name is the part worth keeping.
_FORM_NAME_CHARS = 80


def send_per_form(
    db: Session,
    *,
    link: SheetLink,
    client: SheetsClient,
    leads: Sequence[Lead],
    zone: ZoneInfo | None,
    now: datetime,
) -> None:
    """Append each form's leads to that form's file, making it if it is new.

    A form's file is made on its first lead, so a form nobody fills in
    leaves no empty file behind.
    """
    files: dict[uuid.UUID | None, FormSheet] = {
        sheet.form_id: sheet for sheet in form_sheets_for(db, link=link)
    }
    for form_id, group in _by_form(leads).items():
        target = files.get(form_id)
        if target is None:
            target = _make_file(db, link=link, client=client, lead=group[0])
            files[form_id] = target
        send_rows(
            db,
            link=link,
            client=client,
            target=target,
            leads=group,
            zone=zone,
            now=now,
        )


def _by_form(leads: Sequence[Lead]) -> dict[uuid.UUID | None, list[Lead]]:
    """The leads by form, each group still oldest first."""
    grouped: dict[uuid.UUID | None, list[Lead]] = {}
    for lead in leads:
        grouped.setdefault(lead.form_id, []).append(lead)
    return grouped


def _make_file(
    db: Session, *, link: SheetLink, client: SheetsClient, lead: Lead
) -> FormSheet:
    """A new file for ``lead``'s form, headed like the one-file spreadsheet."""
    form = lead.form
    if form is None:
        title = word("TargetologAI — Boshqa formalar")
    else:
        name = (form.name or word("Forma"))[:_FORM_NAME_CHARS]
        title = f"TargetologAI — {name}"
    sheet = client.create(
        title=title,
        sheet_title=word("Mijozlar"),
        columns=fixed_columns(),
        time_zone=business_timezone(db, owner=link.owner),
    )
    return add_form_sheet(
        db,
        link=link,
        form_id=str(lead.form_id) if lead.form_id else None,
        sheet=sheet,
    )


__all__ = ["send_per_form"]
