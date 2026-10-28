"""Getting each way of writing ready: the files to reuse, make, or add a tab to."""

from googlekit import DriveFile, PermissionMissing, SheetMissing, SheetsClient
from sqlalchemy.orm import Session

from app.modules.businesses.selectors import business_timezone
from app.modules.destinations.constants import SPREADSHEET_MIME, BrokenReason
from app.modules.destinations.models import SheetLink
from app.modules.destinations.selectors import fixed_columns, form_sheets_for, word
from app.modules.destinations.services.file_state import adopt_tab, drop_form_sheets
from app.modules.destinations.services.sheet_state import adopt_sheet

# Sheets refuses a tab name over a hundred characters.
_FORM_NAME_CHARS = 60


def prepare_single(db: Session, *, link: SheetLink, client: SheetsClient) -> str:
    """Reuse the file the link pointed at, or make one. Returns which.

    Inside ``override`` for the owner: a new file is headed in their language.
    """
    if file_opens(
        client=client, spreadsheet_id=link.spreadsheet_id, sheet_id=link.sheet_id
    ):
        return "reused"
    sheet = client.create(
        title=word("TargetologAI — Mijozlar"),
        sheet_title=word("Mijozlar"),
        columns=fixed_columns(),
        time_zone=business_timezone(db, owner=link.owner),
    )
    adopt_sheet(db, link=link, sheet=sheet)
    return "created"


def prepare_own_file(
    db: Session, *, link: SheetLink, client: SheetsClient
) -> str | BrokenReason:
    """Open the owner's picked file and give it a tab of ours, or say why not.

    What is in the file stays as it is. A file in the bin, not a spreadsheet,
    or theirs only to read comes back as the reason, not an error.
    """
    refusal = _refusal(client.file_info(file_id=link.spreadsheet_id))
    if refusal is not None:
        return refusal
    found = client.describe(spreadsheet_id=link.spreadsheet_id)
    if link.sheet_id and link.sheet_id in found.sheet_ids:
        return "reused"
    title = _free_title(_own_title(link), taken=found.titles)
    tab = client.add_tab(
        spreadsheet_id=link.spreadsheet_id, title=title, columns=fixed_columns()
    )
    adopt_tab(db, link=link, sheet_id=tab, url=f"{found.url}#gid={tab}")
    return "tab_added"


def prepare_per_form(db: Session, *, link: SheetLink, client: SheetsClient) -> str:
    """Keep the per-form files that still open, and forget the rest."""
    lost = [
        str(sheet.id)
        for sheet in form_sheets_for(db, link=link)
        if not file_opens(
            client=client, spreadsheet_id=sheet.spreadsheet_id, sheet_id=sheet.sheet_id
        )
    ]
    drop_form_sheets(db, link=link, ids=lost)
    return f"files_lost:{len(lost)}"


def file_opens(*, client: SheetsClient, spreadsheet_id: str, sheet_id: str) -> bool:
    """Whether a file this product made can still be written into."""
    if not spreadsheet_id or not sheet_id:
        return False
    try:
        found = client.describe(spreadsheet_id=spreadsheet_id)
        if sheet_id not in found.sheet_ids:
            return False
        return not client.is_trashed(file_id=spreadsheet_id)
    except (SheetMissing, PermissionMissing):
        return False


def _refusal(found: DriveFile) -> BrokenReason | None:
    if found.trashed:
        return BrokenReason.TRASHED
    if found.mime_type != SPREADSHEET_MIME:
        return BrokenReason.NOT_A_SHEET
    if not found.can_edit:
        return BrokenReason.READ_ONLY
    return None


def _own_title(link: SheetLink) -> str:
    """The tab's name: the product's, and the one form's when there is one."""
    form = link.only_form
    if form is None:
        return word("TargetologAI — Mijozlar")
    name = (form.name or word("Forma"))[:_FORM_NAME_CHARS]
    return f"TargetologAI — {name}"


def _free_title(base: str, *, taken: frozenset[str]) -> str:
    """``base``, or ``base`` with the first counter no tab in the file has."""
    if base not in taken:
        return base
    number = 2
    while f"{base} ({number})" in taken:
        number += 1
    return f"{base} ({number})"


__all__ = ["file_opens", "prepare_own_file", "prepare_per_form", "prepare_single"]
