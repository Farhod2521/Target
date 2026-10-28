"""The waiting list's lines about what last night's diagnosis found."""

from datetime import datetime
from typing import Final, cast
from urllib.parse import urlencode

from adskit import ExternalRef, ProviderName
from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.ads.selectors.library import form_advert
from app.modules.agent.constants import DiagnosisCause
from app.modules.agent.selectors.notes import DiagnosisNote, diagnosis_notes
from app.modules.chat.constants import SCRIPT_ASK
from app.modules.notifications.selectors.inbox_page import InboxPage, built_here
from core.inbox import InboxItem, ItemKind, Subject

_NOTE_KINDS: Final[dict[str, ItemKind]] = {
    DiagnosisCause.TOO_EARLY: "wait",
    DiagnosisCause.WEAK_CREATIVE: "creative",
    DiagnosisCause.WORN_OUT: "creative",
    DiagnosisCause.COSTLY_AUDIENCE: "audience",
    DiagnosisCause.NOT_DELIVERING: "audience",
    DiagnosisCause.LEARNING_LIMITED: "audience",
}

FORM_SIGNALS: Final = frozenset(
    {"long_form", "low_click_to_lead", "conversion_ranking_low"}
)

_NOTE_TITLES: Final[dict[str, str]] = {
    "wait": "Hali erta: «%(name)s»",
    "landing": "Murojaatga forma yoki sayt to'sqinlik qilyapti: «%(name)s»",
    "creative": "Reklamaga yangi rasm yoki video kerak: «%(name)s»",
    "audience": "Auditoriyani kengaytirish kerak: «%(name)s»",
}


def diagnosis_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """What last night's diagnosis found that no proposal answers."""
    account = view.home
    if account is None:
        return []

    items: list[InboxItem] = []
    for note in diagnosis_notes(
        db,
        owner=owner,
        currency=account.currency,
        now=now,
        hidden_adsets=built_here(db, owner=owner, view=view).outside,
    ):
        young = note.cause == DiagnosisCause.TOO_EARLY
        kind = _NOTE_KINDS.get(note.cause, "landing")
        key = f"{kind}:{note.adset_id}:{note.signal}"
        action, href = _next_step(db, owner=owner, kind=kind, key=key, note=note)
        items.append(
            InboxItem(
                key=key,
                kind=kind,
                level=(
                    "news"
                    if young
                    else ("urgent" if note.signal == "site_down" else "decision")
                ),
                title=_NOTE_TITLES[kind] % {"name": note.name},
                body=" ".join(part for part in (note.line, str(note.advice)) if part),
                action=action,
                href=href,
                subject=Subject(
                    ref=ExternalRef(
                        provider=cast("ProviderName", account.provider),
                        level="adset",
                        id=note.adset_id,
                    ),
                    name=note.name,
                ),
            )
        )
    return items


def _next_step(
    db: Session, *, owner: User, kind: str, key: str, note: DiagnosisNote
) -> tuple[str, str]:
    """The button under a line: the chat for a video, the form, or the campaign."""
    if kind == "creative":
        query = urlencode({"item": key, "ask": SCRIPT_ASK})
        return "Chatda video ssenariy yozish", f"{reverse('chat:chat')}?{query}"
    if note.signal in FORM_SIGNALS:
        advert = form_advert(db, owner=owner, adset_external_id=note.adset_id)
        if advert is not None:
            return "Formani almashtirish", reverse(
                "ads:ad_edit", args=[advert.external_id]
            )
    if note.campaign_pk:
        return "Ko'rish", reverse("ads:campaign", args=[note.campaign_pk])
    return "Ko'rish", reverse("ads:campaigns")


__all__ = ["diagnosis_items"]
