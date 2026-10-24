"""The two lists in the digest that are neither adverts nor figures."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.aftermath import comparison
from app.modules.agent.causes import cause_label
from app.modules.agent.constants import (
    RULE_LABELS,
    SuggestionKind,
    SuggestionOutcome,
    SuggestionStatus,
)
from app.modules.agent.models import AgentSuggestion
from app.modules.chat.constants import AUDIENCES_IN_CONTEXT, SUGGESTIONS_IN_CONTEXT
from app.modules.chat.selectors.fence import inside_rows
from core.chat.context import AudienceDigest, SuggestionDigest


def audience_digests(db: Session, *, owner: User) -> tuple[AudienceDigest, ...]:
    """The lists an answer about targeting has to know exist."""
    from app.modules.ads.selectors import page_accounts
    from app.modules.integrations.selectors import audiences

    rows = audiences(db, owner=owner, accounts=page_accounts(db, owner=owner))
    return tuple(
        AudienceDigest(
            name=row.name,
            kind=_audience_kind(row),
            size=f"{row.approximate_count_lower}-{row.approximate_count_upper}",
            is_ready=row.is_ready,
        )
        for row in rows[:AUDIENCES_IN_CONTEXT]
    )


def _audience_kind(row: object) -> str:
    if getattr(row, "is_lookalike", False):
        return "similar"
    if getattr(row, "source_kind", ""):
        return "retargeting"
    return "customer list"


def suggestion_digests(
    db: Session, *, owner: User, currency: str, scope: PageScope
) -> tuple[SuggestionDigest, ...]:
    """What the agent proposed lately, why, and what became of it."""
    rows = inside_rows(
        db,
        owner=owner,
        scope=scope,
        rows=select(AgentSuggestion)
        .where(AgentSuggestion.owner_id == owner.id)
        .order_by(AgentSuggestion.created_at.desc()),
        target=lambda row: (
            row.target_level,
            row.target_external_id,
            row.target_parent_id,
        ),
        limit=SUGGESTIONS_IN_CONTEXT,
    )
    return tuple(
        SuggestionDigest(
            what=(
                f"{SuggestionKind(row.kind).label} "
                f"({RULE_LABELS.get(row.rule, row.rule)})"
            ),
            status=str(SuggestionStatus(row.status).label),
            outcome=str(SuggestionOutcome(row.outcome).label) if row.outcome else "",
            cause=str(cause_label(row.cause)),
            change=_change(row, currency=currency),
        )
        for row in rows
    )


def _change(row: AgentSuggestion, *, currency: str) -> str:
    """The figure the verdict was read from, before and after. Empty before one."""
    if not row.outcome:
        return ""
    found = comparison(
        rule=row.rule,
        evidence=row.evidence,
        after=row.outcome_figures,
        currency=currency,
    )
    if found is None:
        return ""
    return f"{found.label}: {found.before} → {found.after}"


__all__ = ["audience_digests", "suggestion_digests"]
