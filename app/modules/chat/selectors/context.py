"""What the assistant is told about the account, assembled from tables."""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.copy import MATURITY_LABELS
from app.modules.chat.constants import (
    ADS_IN_CONTEXT,
    ADSETS_IN_CONTEXT,
    CAMPAIGNS_IN_CONTEXT,
    CONTEXT_WINDOW_DAYS,
    FORMS_IN_CONTEXT,
    PAGES_IN_CONTEXT,
)
from app.modules.chat.selectors.briefs import (
    account_ads,
    account_adsets,
    account_forms,
    account_pages,
    adset_brief,
)
from app.modules.chat.selectors.choices import Choice
from app.modules.chat.selectors.fence import outside_targets
from app.modules.chat.selectors.page_figures import page_sums, prior_digest
from app.modules.chat.selectors.result_counts import digests, merged
from app.modules.chat.selectors.scope import current_page_scope, subscribed_accounts
from app.modules.chat.selectors.sections import audience_digests, suggestion_digests
from core.chat.context import (
    AccountDigest,
    BusinessDigest,
    CampaignDigest,
    ChatContext,
    FocusDigest,
    OfferDigest,
    PageTotals,
    TotalsDigest,
    TroubleDigest,
)
from core.chat.numbers import figures_in
from core.chat.route import SECTIONS, Section
from core.chat.rungs import AdSetDigest
from core.inbox import InboxItem

EVERYTHING: frozenset[Section] = frozenset(SECTIONS)


def chat_context(
    db: Session,
    *,
    owner: User | None,
    asked: tuple[str, ...] = (),
    focus_id: str = "",
    item_key: str = "",
    wants: frozenset[Section] | None = None,
    offers: tuple[Choice, ...] = (),
    now: datetime | None = None,
    scope: PageScope | None = None,
) -> ChatContext:
    """The context for one question."""
    from app.modules.metrics.selectors.dashboard import cabinet_today

    quoted = figures_in(" ".join(asked))
    if owner is None:
        return ChatContext(account=None, quoted=quoted)
    today = cabinet_today(db, owner=owner)
    scope = scope or current_page_scope(db, owner=owner)
    return ChatContext(
        account=_account(
            db,
            owner=owner,
            wants=EVERYTHING if wants is None else wants,
            today=today,
            scope=scope,
        ),
        quoted=quoted,
        focus=_focus(db, owner=owner, focus_id=focus_id, scope=scope),
        trouble=_trouble(
            db, owner=owner, item_key=item_key, now=now, today=today, scope=scope
        ),
        offers=tuple(
            OfferDigest(
                key=item.key, what=item.label, target=item.target, why=item.rule
            )
            for item in offers
        ),
    )


def _trouble(
    db: Session,
    *,
    owner: User,
    item_key: str,
    now: datetime | None,
    today: date,
    scope: PageScope,
) -> TroubleDigest | None:
    """The one line of the waiting list this question came from, or nothing."""
    from app.modules.notifications.selectors import cached_inbox

    if not item_key or now is None:
        return None
    found = next(
        (row for row in cached_inbox(db, owner=owner, now=now) if row.key == item_key),
        None,
    )
    if found is None:
        return None
    if found.subject is not None and outside_targets(
        db,
        owner=owner,
        scope=scope,
        targets=[(found.subject.ref.level, found.subject.ref.id, "")],
    ):
        return TroubleDigest(
            what=str(found.title),
            detail=str(found.body),
            level=found.level,
            outside=True,
        )
    return TroubleDigest(
        what=str(found.title),
        detail=str(found.body),
        level=found.level,
        target=found.subject.name if found.subject is not None else "",
        about=_about(db, owner=owner, item=found, today=today, scope=scope),
    )


def _about(
    db: Session, *, owner: User, item: InboxItem, today: date, scope: PageScope
) -> AdSetDigest | None:
    if item.subject is None:
        return None
    return adset_brief(db, owner=owner, ref=item.subject.ref, today=today, scope=scope)


def _focus(
    db: Session, *, owner: User, focus_id: str, scope: PageScope
) -> FocusDigest | None:
    """The one proposal being asked about, or nothing."""
    from app.modules.agent.selectors import card_for, one

    if not focus_id:
        return None
    try:
        key = uuid.UUID(focus_id)
    except ValueError:
        return None
    suggestion = one(db, owner=owner, pk=key)
    if suggestion is None:
        return None
    if outside_targets(
        db,
        owner=owner,
        scope=scope,
        targets=[
            (
                suggestion.target_level,
                suggestion.target_external_id,
                suggestion.target_parent_id,
            )
        ],
    ):
        return None
    card = card_for(db, owner=owner, suggestion=suggestion)
    return FocusDigest(
        what=f"{card.kind_label} ({card.rule_label})",
        target=card.target_name,
        status=str(card.status_label),
        reason=card.reason,
        expectation=str(card.expectation),
        figures=tuple((str(label), value) for label, value in card.figures),
        outcome=_became_of(card),
        after=tuple((str(label), value) for label, value in card.after),
        reason_dated=card.reason_dated,
    )


def _became_of(card: Any) -> str:
    if card.landed is False:
        return "the provider accepted the change but the object was unchanged"
    return str(card.outcome_label) if card.outcome_label else ""


def _account(
    db: Session,
    *,
    owner: User,
    wants: frozenset[Section],
    today: date,
    scope: PageScope,
) -> AccountDigest | None:
    """The subscription over the window, cut by Facebook page."""
    from app.modules.agent.selectors import last
    from app.modules.businesses.selectors import business_for, category_label
    from app.modules.metrics.selectors.lead_sources import (
        other_currency_campaigns,
        other_currency_spend,
    )
    from app.modules.metrics.selectors.scope import page_campaigns

    business = business_for(db, owner)
    if business is None:
        return None
    accounts = subscribed_accounts(db, owner=owner)
    account = accounts[0] if accounts else None
    currency = page_campaigns(db, owner=owner).currency or (
        account.currency if account is not None else ""
    )
    since = today - timedelta(days=CONTEXT_WINDOW_DAYS - 1)
    apart = other_currency_campaigns(
        db, owner=owner, ids=scope.campaign_ids, currency=currency
    )
    pages = page_sums(
        db, owner=owner, scope=scope, since=since, until=today, without=apart
    )
    spend = sum(row.spend_minor for row in pages)
    run = last(db, owner=owner)
    return AccountDigest(
        business=BusinessDigest(
            name=business.name,
            category=category_label(business),
            offer=business.offer_text,
            currency=currency,
        ),
        totals=TotalsDigest(
            window_days=CONTEXT_WINDOW_DAYS,
            spend=_money(spend, currency),
            results=digests(
                merged(item for row in pages for item in row.results), currency=currency
            ),
            prior=prior_digest(
                db,
                owner=owner,
                scope=scope,
                since=since,
                days=CONTEXT_WINDOW_DAYS,
                without=apart,
                window=pages,
                currency=currency,
            ),
            other_currency=tuple(
                format_minor(amount_minor=amount, currency=code)
                for code, amount in other_currency_spend(
                    db, owner=owner, ids=apart, since=since, until=today
                )
            ),
        ),
        maturity=str(MATURITY_LABELS.get(getattr(run, "maturity", ""), "")),
        by_page=tuple(
            PageTotals(
                name=row.name,
                spend=_money(row.spend_minor, currency),
                results=digests(row.results, currency=currency),
                campaigns=tuple(
                    CampaignDigest(
                        name=item.name,
                        status=item.status,
                        spend=_money(item.spend_minor, currency),
                        results=digests(item.results, currency=currency),
                    )
                    for item in row.campaigns[:CAMPAIGNS_IN_CONTEXT]
                )
                if "campaigns" in wants
                else (),
            )
            for row in pages
        ),
        adsets=account_adsets(
            db, owner=owner, limit=ADSETS_IN_CONTEXT, scope=scope, today=today
        )
        if "adsets" in wants
        else (),
        ads=account_ads(db, owner=owner, limit=ADS_IN_CONTEXT, scope=scope, today=today)
        if "ads" in wants
        else (),
        forms=account_forms(db, owner=owner, limit=FORMS_IN_CONTEXT, scope=scope)
        if "landing" in wants
        else (),
        pages=account_pages(db, owner=owner, limit=PAGES_IN_CONTEXT)
        if "landing" in wants
        else (),
        audiences=audience_digests(db, owner=owner) if "audiences" in wants else (),
        suggestions=suggestion_digests(db, owner=owner, currency=currency, scope=scope)
        if "suggestions" in wants
        else (),
        omitted=tuple(name for name in SECTIONS if name not in wants),
    )


def _money(amount_minor: int, currency: str) -> str:
    return format_minor(amount_minor=amount_minor, currency=currency) or "0"


__all__ = ["EVERYTHING", "chat_context"]
