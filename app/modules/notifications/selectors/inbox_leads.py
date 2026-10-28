"""Three lines on the waiting list about leads that are not arriving."""

import hashlib
from datetime import datetime

from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.integrations.models import PageAccount
from app.modules.leads.constants import SWEEP_STUCK_DAYS
from app.modules.leads.selectors.reads import stuck_forms
from app.modules.metrics.selectors.lead_gap import (
    GAP_DAYS,
    LeadGap,
    lead_gap,
    unheard_pages,
)
from app.modules.notifications.selectors.inbox_page import InboxPage
from core.inbox import InboxItem

KEY_DIGEST_CHARS = 8


def lead_gap_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """The provider counted leads last week that never arrived here."""
    gaps = [
        gap
        for account in view.accounts
        if (
            gap := lead_gap(
                db,
                owner=owner,
                account=account,
                now=now,
                hidden_adsets=view.scope.outside,
            )
        )
        is not None
    ]
    if not gaps:
        return []
    gap = _together(gaps)

    body = (
        "Oxirgi %(days)d kunda Meta %(reported)d ta murojaat sanadi, bu yerga "
        "%(ours)d tasi yetib keldi."
    ) % {"days": GAP_DAYS, "reported": gap.reported, "ours": gap.ours}
    if gap.pages:
        body += " " + "Sahifa: %(pages)s." % {
            "pages": ", ".join(f"«{name}»" for name in gap.pages)
        }
    body += " " + (
        "Yetib kelmaganlarini «Mijozlar» bo'limida tiklash mumkin. Takrorlansa, "
        "sahifani qayta ulang."
    )
    return [
        InboxItem(
            key=f"lead_gap:{_digest('|'.join(gap.pages))}",
            kind="lead_gap",
            level="decision",
            title="Murojaatlarning bir qismi kabinetga yetib kelmayapti",
            body=body,
            action="Ko'rish",
            href=reverse("leads:sources"),
        )
    ]


def unheard_page_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """A page's form adverts collect leads and none of them arrive here."""
    return [
        InboxItem(
            key=f"unheard:{page.page_id}",
            kind="unheard_page",
            level="decision",
            title="«%(page)s» sahifasining murojaatlari kelmayapti"
            % {"page": page.name},
            body=(
                "Oxirgi %(days)d kunda Meta bu sahifaning reklamalaridan "
                "%(count)d ta murojaat sanadi, lekin sahifa kabinetga murojaat "
                "olish uchun ulanmagan - ular bu yerga tushmaydi. Ulasangiz, "
                "avvalgilari ham olinadi."
            )
            % {"days": GAP_DAYS, "count": page.reported},
            action="Ulash",
            href=reverse("integrations:connect_page_leads", args=[page.page_id]),
            method="post",
        )
        for page in unheard_pages(db, owner=owner, accounts=view.accounts, now=now)
    ]


def stuck_sweep_items(
    db: Session, *, owner: User, page: PageAccount | None, now: datetime
) -> list[InboxItem]:
    """The nightly re-read of a form has failed for days in a row."""
    if page is None:
        return []
    forms = stuck_forms(db, owner=owner, now=now, page=page)
    if not forms:
        return []

    first = forms[0]
    days = (now - first.swept_at).days if first.swept_at else SWEEP_STUCK_DAYS
    body = (
        "«%(form)s» formasidagi murojaatlarni (%(page)s sahifasi) %(days)d kundan "
        "beri qayta tekshirib bo'lmayapti - kelmay qolganlari qaytarilmayapti."
    ) % {"form": first.name, "page": first.page_name, "days": days}
    if len(forms) > 1:
        others = len(forms) - 1
        body += " " + "Yana %(count)d ta forma shu holatda." % {"count": others}
    body += " " + "Ulanishni yangilash odatda yordam beradi."
    return [
        InboxItem(
            key=f"sweep:{_digest('|'.join(str(form.pk) for form in forms))}",
            kind="sweep",
            level="decision",
            title="Murojaatlarni qayta tekshirish to'xtab qolgan",
            body=body,
            since=first.swept_at,
            action="Ulanishlar",
            href=reverse("integrations:connections"),
        )
    ]


def _together(gaps: list[LeadGap]) -> LeadGap:
    """Several accounts' weeks for one page, as the one week the owner sees."""
    return LeadGap(
        reported=sum(gap.reported for gap in gaps),
        ours=sum(gap.ours for gap in gaps),
        missing=sum(gap.missing for gap in gaps),
        pages=tuple(dict.fromkeys(page for gap in gaps for page in gap.pages)),
        since=min(gap.since for gap in gaps),
        until=max(gap.until for gap in gaps),
    )


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:KEY_DIGEST_CHARS]


__all__ = ["lead_gap_items", "stuck_sweep_items", "unheard_page_items"]
