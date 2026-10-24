"""The lead forms of the subscription's pages, and what each has collected."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.lookups.common import named, section, window
from app.modules.chat.selectors.scope import lead_window
from app.modules.integrations.models import PageAccount
from app.modules.leads.constants import LeadFormStatus
from app.modules.leads.models import Lead, LeadForm
from core.chat.lookups import FORM_ROWS, FormList

RECENT_DAYS: Final = 30


def lead_forms(
    db: Session, *, owner: User, arguments: FormList, scope: PageScope, now: datetime
) -> str:
    """Forms, newest first, with their questions and how many leads each brought."""
    query = (
        select(LeadForm)
        .join(PageAccount, PageAccount.id == LeadForm.page_id)
        .where(
            LeadForm.owner_id == owner.id,
            PageAccount.is_active.is_(True),
            PageAccount.external_id.in_(list(scope.pages)),
        )
    )
    if arguments.page_id:
        query = query.where(PageAccount.external_id == arguments.page_id)
    forms = list(
        db.scalars(
            query.order_by(LeadForm.created_time.desc().nulls_last()).limit(FORM_ROWS)
        )
    )
    counts: dict[Any, Mapping[str, Any]] = {}
    running: dict[str, int] = {}
    if forms:
        since, until = window(db, owner=owner, days=RECENT_DAYS)
        start, _end = lead_window(db, owner=owner, since=since, until=until)
        counts = {
            row["form_id"]: row
            for row in db.execute(
                select(
                    Lead.form_id,
                    func.count(Lead.id).label("total"),
                    func.count(Lead.id)
                    .filter(Lead.submitted_at >= start)
                    .label("recent"),
                    func.max(Lead.submitted_at).label("last"),
                )
                .where(
                    Lead.owner_id == owner.id,
                    Lead.form_id.in_([form.id for form in forms]),
                    Lead.is_test.is_(False),
                )
                .group_by(Lead.form_id)
            ).mappings()
        }
        running = dict(
            db.execute(
                select(Ad.lead_form_external_id, func.count(Ad.id))
                .where(
                    Ad.owner_id == owner.id,
                    Ad.delivery == Delivery.ACTIVE,
                    Ad.lead_form_external_id.in_([form.external_id for form in forms]),
                )
                .group_by(Ad.lead_form_external_id)
            ).all()
        )
    lines = [
        _line(
            form,
            counts=counts.get(form.id, {}),
            running=running.get(form.external_id, 0),
        )
        for form in forms
    ]
    return "\n".join(section("Lead forms", lines, empty="no forms on these pages"))


def _status(value: str) -> str:
    try:
        return str(LeadFormStatus(value).label)
    except ValueError:
        return value


def _line(form: LeadForm, *, counts: Mapping[str, Any], running: int) -> str:
    from app.modules.leads.selectors import question_summary

    parts = [
        _status(form.status),
        f"running adverts using it {running}",
        f"leads received in the last {RECENT_DAYS} days {counts.get('recent', 0)}",
        f"all time {counts.get('total', 0)}",
    ]
    if form.leads_count is not None:
        parts.append(f"the provider's total {form.leads_count}")
    if counts.get("last"):
        parts.append(f"last one {counts['last']:%Y-%m-%d}")
    questions = question_summary(form.questions_raw)
    line = (
        f"- {named(form.name, form.external_id)} (id {form.external_id}) on page "
        f"{named(form.page.name, form.page.external_id)} - " + ", ".join(parts)
    )
    if questions:
        line += f"; asks: {'; '.join(questions)}"
    return line


__all__ = ["lead_forms"]
