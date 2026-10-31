"""A refused press in the shape every screen draws, whichever module it came from.

Called where a provider's refusal is caught and a person is waiting for the
answer: a background read keeps its own quiet ``except`` and never comes here,
so nothing an owner did not press can cost a question to Claude.
"""

import logging
from collections.abc import Sequence
from typing import Any, Final

from adskit.errors import ProviderError
from sqlalchemy.orm import Session

from app.common.contract import Refusal, RefusalAnswer, RefusalFix
from app.common.exceptions import ProviderRefused
from app.common.i18n import get_language
from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.chat.selectors.change_refusal import MEANINGS, change_links
from app.modules.chat.selectors.refusal import (
    already_asked,
    answer_language,
    awaited,
    ready_answer,
)
from app.modules.chat.services.explain import explain_action_later
from app.modules.integrations.models import AdAccount
from core.chat.links import Link, link_html
from core.chat.markdown import render as render_markdown
from core.chat.refusal import ChangeFacts

logger = logging.getLogger(__name__)

# What the owner pressed, in the model's language, and the dialog's title.
OPERATIONS: Final[dict[str, str]] = {
    "media": "sending a picture or video to the Meta library, or taking one off it",
    "audience": "making or removing a custom or lookalike audience",
    "place": "searching for a place to advertise in",
    "connect": "connecting their Meta account to this product",
    "review": "running an advert that Meta's review or delivery turned down",
}
TITLES: Final[dict[str, str]] = {
    "media": "Meta faylni qabul qilmadi",
    "audience": "Meta auditoriyani qabul qilmadi",
    "place": "Meta joyni qidirishni rad etdi",
    "connect": "Meta ulanishni rad etdi",
    "review": "Meta reklamani rad etdi",
}
# What a missing object is, by what was pressed: the sentence for a change speaks of an advert.
MISSING: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "media": (
        "Bu fayl Meta kutubxonasida topilmadi. U Ads Manager'da o'chirilgan bo'lishi mumkin.",
        ("Sahifani yangilang.", "Faylni qayta tanlang yoki qayta yuklang."),
    ),
    "audience": (
        "Bu auditoriya Meta'da topilmadi. U Ads Manager'da o'chirilgan bo'lishi mumkin.",
        ("Sahifani yangilang.", "Kerak bo'lsa, auditoriyani qayta yarating."),
    ),
}
BUSY_TITLE: Final = "Meta hozir javob bermadi"
NO_REASON: Final = "Meta aniq sababini aytmadi."


def refusal_for(
    db: Session,
    *,
    owner: User,
    exc: ProviderError,
    operation: str,
    account: AdAccount | None = None,
) -> Refusal:
    """What to tell the owner: a passing fault, a written sentence, or an answer."""
    from app.modules.ads.selectors.failures import (
        SENTENCES,
        UNNAMED_STEPS,
        fix_link,
        guide_of,
    )
    from app.modules.ads.services.manage import provider_failure

    words = _words(exc)
    if exc.retryable:
        return Refusal(
            retryable=True,
            title=BUSY_TITLE,
            cause=guide_of("temporary")[0],
            steps=list(guide_of("temporary")[1]),
            provider_words=words,
            retry_after_seconds=getattr(exc, "retry_after_seconds", 0) or None,
        )
    title = TITLES[operation]
    code = provider_failure(exc, account)
    if code in SENTENCES:
        link = fix_link(
            SENTENCES[code][1], account.external_id if account is not None else ""
        )
        cause, steps = (code == "not_found" and MISSING.get(operation)) or guide_of(
            code
        )
        return Refusal(
            title=title,
            cause=cause,
            steps=list(steps),
            provider_words=words,
            fix=RefusalFix(label=link[0], url=link[1]) if link[1] else None,
        )
    key = f"{operation}:{exc.key}" if exc.key else ""
    language = answer_language(owner.language or get_language())
    ready = ready_answer(db, key=key, language=language)
    if key:
        _note(
            key=key,
            owner=owner,
            facts=_facts(
                operation=operation,
                level="their ad account",
                title=exc.user_title,
                message=exc.user_message,
                developer=str(exc),
            ),
            language=language,
            answered=ready is not None,
        )
    return Refusal(
        key=key or None,
        title=title,
        cause=words or NO_REASON,
        steps=list(UNNAMED_STEPS),
        provider_words=words,
        html=_html(ready.text, _links(account)) if ready is not None else None,
        explaining=bool(key) and ready is None and awaited(key=key),
    )


def refused(
    db: Session,
    *,
    owner: User,
    exc: ProviderError,
    operation: str,
    account: AdAccount | None = None,
) -> ProviderRefused:
    """The refusal to raise from a route the owner is waiting on."""
    found = refusal_for(db, owner=owner, exc=exc, operation=operation, account=account)
    return ProviderRefused(found.cause, refusal=found.model_dump(by_alias=True))


def kept_refusal(
    db: Session,
    *,
    owner: User,
    exc: ProviderError,
    operation: str,
    account: AdAccount | None = None,
) -> dict[str, Any]:
    """The refusal to keep on a row and read later, marked to ask for its answer.

    Whatever is written by then belongs to ``GET /refusals/answer``, not to the
    row: the office may correct it after the row was written.
    """
    found = refusal_for(db, owner=owner, exc=exc, operation=operation, account=account)
    return found.model_copy(
        update={"html": None, "explaining": bool(found.key)}
    ).model_dump(by_alias=True)


def explain_rejections(db: Session, *, owner: User, ads: Sequence[Any]) -> None:
    """Ask once about each complaint the sync found with no answer kept.

    The one question nobody pressed for: the sync sees a turned-down advert
    first, and the owner then opens a written answer. The price follows
    Meta's policies, not the owners, because the answer is kept for everyone.
    """
    from app.modules.ads.selectors.rejections import complaint_of, review_key

    language = answer_language(owner.language or get_language())
    for ad in ads:
        key = review_key(ad)
        if not key or already_asked(db, key=key):
            continue
        said = complaint_of(ad)
        try:
            explain_action_later(
                key=key,
                owner=owner,
                facts=_facts(operation="review", level="one advert", message=said),
                language=language,
            )
        except Exception:
            logger.exception("rejection %s was not sent to be explained", key)


def answer_for(
    db: Session, *, key: str, language: str, account: AdAccount | None
) -> RefusalAnswer:
    """The answer a dialog is waiting for, with this owner's own links."""
    ready = ready_answer(db, key=key, language=answer_language(language))
    if ready is None:
        return RefusalAnswer(key=key, explaining=awaited(key=key))
    return RefusalAnswer(key=key, html=_html(ready.text, _links(account)))


def _facts(
    *,
    operation: str,
    level: str,
    title: str = "",
    message: str = "",
    developer: str = "",
) -> ChangeFacts:
    return ChangeFacts(
        change=OPERATIONS[operation],
        level=level,
        provider_title=title,
        provider_message=message,
        developer_message=developer,
        links=tuple(MEANINGS.items()),
    )


def _note(
    *, key: str, owner: User, facts: ChangeFacts, language: str, answered: bool
) -> None:
    """Count the refusal and ask for its answer, in the worker.

    The route is about to raise and roll back, so nothing here can be its
    write; and a lost broker must not turn a refusal into a server error.
    """
    from app.modules.chat.tasks import count_action_refusal

    try:
        count_action_refusal.delay(key)
        if not answered:
            explain_action_later(key=key, owner=owner, facts=facts, language=language)
    except Exception:
        logger.exception("refusal %s was not sent to be explained", key)


def _words(exc: ProviderError) -> str | None:
    said = " — ".join(part for part in (exc.user_title, exc.user_message) if part)
    return said or None


def _links(account: AdAccount | None) -> dict[str, Link]:
    if account is not None:
        return change_links(account.external_id)
    return {"ulanish": Link("Ulanishlar", reverse("integrations:connections"))}


def _html(text: str, links: dict[str, Link]) -> str:
    return link_html(render_markdown(text), links)


__all__ = [
    "OPERATIONS",
    "answer_for",
    "explain_rejections",
    "kept_refusal",
    "refusal_for",
    "refused",
]
