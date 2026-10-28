"""Stored facts about the files a link writes into, beyond the one it points at.

None is conditional on the link's state: what Google made, or found gone,
stays true whatever the owner pressed meanwhile.
"""

import uuid
from collections.abc import Sequence

from googlekit import Spreadsheet
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.modules.destinations.constants import FIRST_TAB, Channel
from app.modules.destinations.models import FormSheet, LeadDelivery, SheetLink


def adopt_tab(db: Session, *, link: SheetLink, sheet_id: str, url: str) -> None:
    """Point the link at a tab of ours added to the owner's own file.

    A new tab is a new place to write, so every delivery is forgotten.
    """
    db.execute(
        delete(LeadDelivery)
        .where(
            LeadDelivery.owner_id == link.owner_id,
            LeadDelivery.channel == Channel.SHEETS,
        )
        .execution_options(synchronize_session=False)
    )
    link.sheet_id = sheet_id
    link.spreadsheet_url = url
    link.columns = []
    db.commit()


def add_form_sheet(
    db: Session, *, link: SheetLink, form_id: str | None, sheet: Spreadsheet
) -> FormSheet:
    """Record the file just made for one form."""
    row = FormSheet(
        owner_id=link.owner_id,
        form_id=uuid.UUID(form_id) if form_id else None,
        spreadsheet_id=sheet.spreadsheet_id,
        sheet_id=sheet.sheet_ids[0] if sheet.sheet_ids else FIRST_TAB,
        spreadsheet_url=sheet.url,
        columns=[],
    )
    db.add(row)
    db.commit()
    return row


def drop_form_sheets(db: Session, *, link: SheetLink, ids: Sequence[str]) -> int:
    """Forget per-form files that are gone. Their deliveries go with them."""
    if not ids:
        return 0
    keys = [uuid.UUID(value) for value in ids]
    # Django's cascade is its own, not the database's: the rows go first.
    db.execute(
        delete(LeadDelivery)
        .where(
            LeadDelivery.owner_id == link.owner_id,
            LeadDelivery.form_sheet_id.in_(keys),
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(
        delete(FormSheet)
        .where(FormSheet.owner_id == link.owner_id, FormSheet.id.in_(keys))
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def grow_columns(
    db: Session, *, target: SheetLink | FormSheet, questions: Sequence[str]
) -> None:
    """Record question columns a file now has, after the fixed ones."""
    target.columns = [*target.columns, *questions]
    db.commit()


__all__ = ["add_form_sheet", "adopt_tab", "drop_form_sheets", "grow_columns"]
