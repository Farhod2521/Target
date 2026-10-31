"""A refused launch, read for the conversation that explains it."""

import uuid
from dataclasses import dataclass
from typing import Any

from metaads.accounts import ACCOUNT_QUALITY_URL, IDENTITY_URL, billing_url, manager_url
from metaads.leadforms import terms_url
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.i18n import DEFAULT, LANGUAGES
from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.ads.constants import LaunchStatus, LaunchStep
from app.modules.ads.contract.launch.words import failure_code_of
from app.modules.ads.models import CampaignLaunch
from app.modules.chat.constants import (
    OUR_FAULT_KEYS,
    REFUSAL_ANSWER_FIELDS,
    REFUSAL_STALE_VERSIONS,
)
from app.modules.chat.models import RefusalAnswer
from core.chat.context import as_quote
from core.chat.links import Link
from core.chat.refusal import RefusalFacts, refusal_key

REFUSED = (LaunchStatus.FAILED, LaunchStatus.ROLLED_BACK)
SECTIONS = (
    ("The owner's answers in the wizard", "answers"),
    ("The advert as drafted", "draft"),
    ("The audience as sent", "targeting"),
    ("The ad groups", "ad_groups"),
)


def refused_launch_for(
    db: Session, *, owner: User, launch_id: str
) -> CampaignLaunch | None:
    """This owner's launch that went wrong, or nothing."""
    if not launch_id:
        return None
    try:
        key = uuid.UUID(str(launch_id))
    except ValueError:
        return None
    return db.scalar(
        select(CampaignLaunch).where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.status.in_(REFUSED),
            CampaignLaunch.error_code != "",
            CampaignLaunch.id == key,
        )
    )


def key_for(launch: CampaignLaunch) -> str:
    """The name this refusal's ready answer is kept under, or empty."""
    named = str(_detail(launch).get("key") or "")
    if named:
        return named
    return refusal_key(
        provider=launch.provider,
        error_code=launch.error_code,
        error_message=launch.error_message,
    )


def explained_key(launch: CampaignLaunch) -> str:
    """The key of a refusal the sheet has no answer of its own for, or empty.

    A named refusal has its steps written already, and a passing fault is
    answered by waiting: neither is worth a question to Claude.
    """
    return key_for(launch) if failure_code_of(launch.error_code) == "other" else ""


@dataclass(frozen=True, slots=True)
class ReadyAnswer:
    """A stored answer in the reader's language, and the row it came from."""

    pk: Any
    text: str


def answer_language(language: str | None) -> str:
    """The language an answer is read and written in: one with a column."""
    code = (language or "").split("-")[0].lower()
    if code not in LANGUAGES:
        code = DEFAULT
    return code if code in REFUSAL_ANSWER_FIELDS else DEFAULT


def ready_answer(db: Session, *, key: str, language: str) -> ReadyAnswer | None:
    """The answer already written for this refusal, in this language first.

    A row with only another language's text answers in that one: asking Claude
    again for a translation is the office's to do, not a reader's to trigger.
    """
    if not key:
        return None
    row = db.scalar(
        select(RefusalAnswer).where(
            RefusalAnswer.key == key,
            RefusalAnswer.held.is_(False),
            RefusalAnswer.prompt_version.not_in(list(REFUSAL_STALE_VERSIONS)),
        )
    )
    if row is None:
        return None
    wanted = REFUSAL_ANSWER_FIELDS[answer_language(language)]
    for field in (wanted, *REFUSAL_ANSWER_FIELDS.values()):
        text = getattr(row, field)
        if text:
            return ReadyAnswer(pk=row.id, text=text)
    return None


def already_asked(db: Session, *, key: str) -> bool:
    """Whether Claude has answered this refusal: a kept row that is not retired."""
    return (
        db.scalar(
            select(RefusalAnswer.id).where(
                RefusalAnswer.key == key,
                RefusalAnswer.prompt_version.not_in(list(REFUSAL_STALE_VERSIONS)),
            )
        )
        is not None
    )


def refusal_facts(launch: CampaignLaunch) -> RefusalFacts:
    """Everything known about the refused launch, for the model."""
    from app.modules.chat.selectors.lookups.common import money

    detail = _detail(launch)
    answers = launch.answers if isinstance(launch.answers, dict) else {}
    budget = (
        money(launch.daily_budget_minor, launch.currency)
        if launch.daily_budget_minor is not None and launch.currency
        else ""
    )
    return RefusalFacts(
        error_code=launch.error_code,
        provider_title=str(detail.get("title") or ""),
        provider_message=str(detail.get("message") or ""),
        developer_message=launch.error_message,
        step=_step_label(launch.step),
        goal=str(answers.get("goal") or ""),
        budget=budget,
        page=launch.page.name if launch.page is not None else "",
        ad_account=launch.ad_account.name if launch.ad_account_id else "",
        sections={
            title: value
            for title, column in SECTIONS
            if (value := getattr(launch, column, None))
        },
        links=tuple((name, MEANINGS[name]) for name in refusal_links(launch)),
        our_fault=key_for(launch) in OUR_FAULT_KEYS,
    )


def _step_label(step: str) -> str:
    if not step:
        return ""
    try:
        return str(LaunchStep(step).label)
    except ValueError:
        return step


MEANINGS = {
    "reklama": "this advert's page here, with the retry button at the bottom",
    "reja": "this advert's settings here: goal, budget, phone, website, chat",
    "media": "this advert's picture and video here",
    "forma": "this advert's lead form here",
    "ulanish": "the Meta connection here, where Meta is connected again",
    "tolov": "Meta's billing page for this ad account: cards, bills",
    "ads_manager": "Meta Ads Manager, opened on this ad account",
    "lid_shartlari": "Meta's lead ads terms for this Facebook page",
    "akkaunt_sifati": "Meta's account quality page: restrictions and appeals",
    "shaxs": "Meta's identity confirmation, needed for political ads",
}


def refusal_links(launch: CampaignLaunch) -> dict[str, Link]:
    """Every address an answer about this launch may point at."""
    pk = launch.id
    account = launch.ad_account.external_id if launch.ad_account_id else ""
    links = {
        "reklama": Link("Reklama sahifasi", reverse("ads:launch_review", args=[pk])),
        "reja": Link("Reklama sozlamalari", reverse("ads:launch_plan", args=[pk])),
        "media": Link("Rasm va video", reverse("ads:launch_media", args=[pk])),
        "forma": Link("Forma", reverse("ads:launch_form", args=[pk])),
        "ulanish": Link("Ulanishlar", reverse("integrations:connections")),
        "tolov": Link("To'lov sahifasini ochish", billing_url(account)),
        "ads_manager": Link("Ads Manager'ni ochish", manager_url(account)),
        "akkaunt_sifati": Link("Akkaunt holati (Meta)", ACCOUNT_QUALITY_URL),
        "shaxs": Link("Shaxsni tasdiqlash (Meta)", IDENTITY_URL),
    }
    if launch.page is not None:
        links["lid_shartlari"] = Link(
            "Shartlarni ochish", terms_url(launch.page.external_id)
        )
    return links


def awaited(*, key: str) -> bool:
    """Whether an answer for this key may still come: none was given up on today."""
    from app.common.cache import cache
    from app.modules.chat.constants import REFUSAL_GAVE_UP, REFUSAL_LOCK

    return bool(cache.get(REFUSAL_LOCK.format(key=key)) != REFUSAL_GAVE_UP)


@dataclass(frozen=True, slots=True)
class Explanation:
    """The written answer under a refusal, or that one is being written."""

    html: str = ""
    explaining: bool = False
    key: str = ""


def launch_explanation(
    db: Session, *, launch: CampaignLaunch, language: str
) -> Explanation:
    """A refused launch's answer as HTML with the owner's own links."""
    from core.chat.links import link_html
    from core.chat.markdown import render as render_markdown

    key = explained_key(launch) if launch.status in REFUSED else ""
    if not key:
        return Explanation()
    ready = ready_answer(db, key=key, language=language)
    if ready is None:
        return Explanation(explaining=awaited(key=key), key=key)
    return Explanation(
        html=link_html(render_markdown(ready.text), refusal_links(launch)), key=key
    )


def refusal_quote(launch: CampaignLaunch) -> dict[str, str]:
    """The card drawn above the question: what was refused, in Meta's words."""
    detail = _detail(launch)
    said = " — ".join(
        part
        for part in (str(detail.get("title") or ""), str(detail.get("message") or ""))
        if part
    )
    return as_quote(
        title="Reklama yaratilmadi",
        body=said or launch.error_message,
        target=launch.campaign_name
        or (launch.page.name if launch.page is not None else ""),
    )


def _detail(launch: CampaignLaunch) -> dict[str, Any]:
    return launch.error_detail if isinstance(launch.error_detail, dict) else {}


__all__ = [
    "MEANINGS",
    "Explanation",
    "ReadyAnswer",
    "already_asked",
    "answer_language",
    "awaited",
    "explained_key",
    "key_for",
    "launch_explanation",
    "ready_answer",
    "refusal_facts",
    "refusal_links",
    "refusal_quote",
    "refused_launch_for",
]
