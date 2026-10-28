"""The waiting list's lines in the provider's voice: refusals, faults, advice, grades."""

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import zip_longest
from typing import cast

from adskit import ExternalRef, ProviderName
from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.ads.selectors.failures import cause_line
from app.modules.ads.selectors.provider_notes import (
    ACCOUNT_NOTES,
    REFUSAL,
    ProviderNote,
    account_advice,
    account_notes,
)
from app.modules.ads.troubles import known
from app.modules.agent.selectors.suggestions import unanswered, waiting
from app.modules.integrations.models import AdAccount
from app.modules.metrics.selectors.creative_rankings import RANKING_DAYS
from app.modules.metrics.selectors.facts import LowRanking, low_rankings
from app.modules.notifications.selectors.inbox_page import InboxPage, built_here
from core.inbox import InboxItem, Subject

REFUSAL_DIGEST_CHARS = 8
RANKINGS_IN_LIST = 3


def refusal_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """What the provider says is wrong with something running, unless a fix waits on it."""
    answered = {
        row.target_external_id
        for row in [
            *waiting(db, owner=owner, now=now),
            *unanswered(db, owner=owner, now=now),
        ]
    }
    scope = built_here(db, owner=owner, view=view)
    notes = _interleaved(
        [
            account_notes(
                db, owner=owner, ad_account=account, answered=answered, scope=scope
            )
            for account in view.accounts
        ],
        limit=ACCOUNT_NOTES,
    )
    items = []
    for note in notes:
        title, body = _said(note)
        items.append(
            InboxItem(
                key=_note_key(note),
                kind="refusal" if note.kind == REFUSAL else "trouble",
                level="urgent",
                title=title,
                body=body,
                action="Reklamani ochish",
                href=(
                    reverse("ads:campaign", args=[note.campaign_pk])
                    if note.campaign_pk
                    else reverse("ads:campaigns")
                ),
                subject=Subject(ref=note.ref, name=_where(note), code=note.code),
            )
        )
    return items


def _said(note: ProviderNote) -> tuple[str, str]:
    """The heading in this product's words, and the provider's own below it."""
    if note.kind != REFUSAL and known(note.code) is not None:
        return note.title, note.body if note.body != note.title else ""
    words = (
        f"{note.title}: {note.body}"
        if note.kind == REFUSAL
        else (note.body or note.title)
    )
    quoted = "Meta'ning so'zlari: %(words)s" % {"words": words}
    if note.kind != REFUSAL:
        return "Meta reklamani to'xtatgan", quoted
    return "Meta reklamani rad etdi", f"{cause_line(words)} {quoted}"


def _where(note: ProviderNote) -> str:
    """Which advert this is about, and how many others share the fault."""
    if not note.others:
        return note.where
    return "%(name)s va yana %(count)d ta guruhda" % {
        "name": note.where,
        "count": note.others,
    }


def _note_key(note: ProviderNote) -> str:
    """One verdict, read once - and again if the provider changes its words."""
    canonical = f"{note.kind}|{note.where}|{note.others}|{note.title}|{note.body}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"refusal:{digest[:REFUSAL_DIGEST_CHARS]}"


def advice_items(db: Session, *, owner: User, view: InboxPage) -> list[InboxItem]:
    """What the provider itself suggests would work better. News, always."""
    scope = built_here(db, owner=owner, view=view)
    notes = _interleaved(
        [
            account_advice(db, owner=owner, ad_account=account, scope=scope)
            for account in view.accounts
        ],
        limit=ACCOUNT_NOTES,
    )
    return [
        InboxItem(
            key=_note_key(note),
            kind="advice",
            level="news",
            title=note.title,
            body=note.body if note.body != note.title else "",
            action="Ko'rish",
            href=reverse("ads:campaigns"),
            subject=Subject(ref=note.ref, name=_where(note), code=note.code),
        )
        for note in notes
    ]


def ranking_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """Adverts the provider has placed in the bottom fifth or worse."""
    return _interleaved(
        [
            [
                _ranking(row=row, provider=account.provider)
                for row in _low(db, owner=owner, account=account, view=view, now=now)
            ]
            for account in view.accounts
        ],
        limit=RANKINGS_IN_LIST,
    )


def _interleaved[Row](rows: list[Sequence[Row]], *, limit: int) -> list[Row]:
    """One account's turn, then the next's, up to ``limit``."""
    return [row for turn in zip_longest(*rows) for row in turn if row is not None][
        :limit
    ]


def _low(
    db: Session, *, owner: User, account: AdAccount, view: InboxPage, now: datetime
) -> tuple[LowRanking, ...]:
    today = now.astimezone(account.tzinfo()).date()
    return low_rankings(
        db,
        owner=owner,
        since=today - timedelta(days=RANKING_DAYS - 1),
        until=today,
        account=account,
        hidden_campaigns=built_here(db, owner=owner, view=view).blocked,
    )


def _ranking(*, row: LowRanking, provider: str) -> InboxItem:
    return InboxItem(
        key=f"ranking:{row.external_id}:{row.verdict}",
        kind="ranking",
        level="news",
        title="Reklama zaif baholanmoqda",
        body=(
            "«%(name)s» - Meta uni shu odamlarga ko'rsatilgan boshqa "
            "reklamalar bilan solishtirib «%(verdict)s» dedi."
        )
        % {"name": row.name, "verdict": row.verdict},
        action="Ko'rish",
        href=reverse("ads:campaigns"),
        subject=Subject(
            ref=ExternalRef(
                provider=cast("ProviderName", provider),
                level="ad",
                id=row.external_id,
            ),
            name=row.name,
        ),
    )


__all__ = ["advice_items", "ranking_items", "refusal_items"]
