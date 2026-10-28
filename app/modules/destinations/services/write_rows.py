"""Appending a batch of leads to one file, and recording that they went."""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from googlekit import GoogleError, RateLimited, SheetsClient, Unavailable
from sqlalchemy.orm import Session

from app.modules.ads.selectors import ad_labels, campaign_names
from app.modules.destinations.constants import FIRST_TAB
from app.modules.destinations.models import FormSheet, SheetLink
from app.modules.destinations.selectors import (
    FIXED_COLUMN_COUNT,
    question_columns,
    sheet_batch,
)
from app.modules.destinations.services.file_state import grow_columns
from app.modules.destinations.services.sheet_state import begin_sending, confirm, forget
from app.modules.leads.models import Lead

# Where rows go: the link's own file, or one of its per-form files.
type Target = SheetLink | FormSheet


def send_rows(
    db: Session,
    *,
    link: SheetLink,
    client: SheetsClient,
    target: Target,
    leads: Sequence[Lead],
    zone: ZoneInfo | None,
    now: datetime,
) -> None:
    """Append ``leads`` to ``target`` and confirm them.

    The records are committed before the rows leave. A refusal forgets them
    at once; anything that may have written the rows leaves them for the
    next run to settle.
    """
    batch = sheet_batch(
        leads=leads,
        known=target.columns,
        zone=zone,
        **_names(db, link=link, leads=leads),
    )
    if batch.new_questions:
        _add_questions(db, client=client, target=target, questions=batch.new_questions)
    begin_sending(
        db,
        link=link,
        lead_ids=batch.lead_ids,
        now=now,
        form_sheet_id=_file_key(target),
    )
    try:
        client.append(
            spreadsheet_id=target.spreadsheet_id,
            sheet_id=tab_of(target),
            rows=batch.rows,
        )
    except GoogleError as exc:
        if _refused_whole(exc):
            forget(db, link=link, lead_ids=batch.lead_ids)
        raise
    confirm(db, link=link, lead_ids=batch.lead_ids, now=now)


def tab_of(target: Target) -> str:
    """The tab's id. Set on every file rows go to - it is recorded with the file."""
    return target.sheet_id or FIRST_TAB


def _file_key(target: Target) -> str | None:
    return str(target.id) if isinstance(target, FormSheet) else None


def _refused_whole(error: GoogleError) -> bool:
    """Whether nothing of the batch can have been written.

    Every refusal, a rate limit included; not a timeout, a dropped
    connection or a 5xx, which may have written the rows and lost the answer.
    """
    return isinstance(error, RateLimited) or not isinstance(error, Unavailable)


def _add_questions(
    db: Session, *, client: SheetsClient, target: Target, questions: Sequence[str]
) -> None:
    """Headings for new questions at the right, then the record of them."""
    client.add_columns(
        spreadsheet_id=target.spreadsheet_id,
        sheet_id=tab_of(target),
        start=FIXED_COLUMN_COUNT + len(target.columns),
        columns=question_columns(questions),
    )
    grow_columns(db, target=target, questions=questions)


def _names(
    db: Session, *, link: SheetLink, leads: Sequence[Lead]
) -> dict[str, dict[str, str]]:
    """What the batch's adverts and campaigns are called: two queries."""
    labels = ad_labels(
        db, owner=link.owner, external_ids=[lead.ad_external_id for lead in leads]
    )
    return {
        "ad_names": {key: label.title for key, label in labels.items()},
        "campaign_names": campaign_names(
            db,
            owner=link.owner,
            external_ids=[lead.campaign_external_id for lead in leads],
        ),
    }


__all__ = ["Target", "send_rows", "tab_of"]
