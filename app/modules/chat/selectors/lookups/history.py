"""What was changed, what the agent proposed, and what is waiting now."""

from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.aftermath import comparison
from app.modules.agent.causes import cause_label
from app.modules.agent.constants import (
    OPEN_STATUSES,
    RULE_LABELS,
    SuggestionKind,
    SuggestionOutcome,
    SuggestionStatus,
)
from app.modules.agent.models import AgentSuggestion
from app.modules.audit.constants import ActionStatus, ActionType, ActorType
from app.modules.audit.models import ActionLog
from app.modules.chat.selectors.fence import inside_rows, outside_targets
from app.modules.chat.selectors.lookups.common import (
    LEVEL_WORDS,
    named,
    names_by_level,
    section,
    subscribed_accounts,
    trimmed,
)
from core.chat.lookups import (
    CHANGE_ROWS,
    PROBLEM_ROWS,
    PROPOSAL_ROWS,
    Nothing,
    Proposals,
    Window,
)

NOTE_CHARS: Final = 240


def _label(choices: type, value: str) -> str:
    try:
        return str(choices(value).label)
    except ValueError:
        return value


def recent_changes(
    db: Session, *, owner: User, arguments: Window, scope: PageScope, now: datetime
) -> str:
    """Changes over the window, newest first, and who made each."""
    rows = inside_rows(
        db,
        owner=owner,
        scope=scope,
        rows=select(ActionLog)
        .where(
            ActionLog.owner_id == owner.id,
            ActionLog.created_at >= now - timedelta(days=arguments.days),
        )
        .order_by(ActionLog.created_at.desc()),
        target=lambda row: (row.target_level, row.target_external_id, ""),
        limit=CHANGE_ROWS,
    )
    names = names_by_level(
        db,
        owner=owner,
        targets=[(row.target_level, row.target_external_id) for row in rows],
    )
    lines = []
    for row in rows:
        level, target = row.target_level, row.target_external_id
        line = (
            f"- {row.created_at:%Y-%m-%d %H:%M} UTC: {_label(ActionType, row.action)} - "
            f"{LEVEL_WORDS.get(level, level)} "
            f"{named(names.get((level, target), ''), target)}"
            f" - by {_label(ActorType, row.actor_type)}, {_label(ActionStatus, row.status)}"
        )
        if row.dry_run:
            line += ", a test run that changed nothing at the provider"
        if row.reason:
            line += f", note: {trimmed(row.reason, NOTE_CHARS)}"
        lines.append(line)
    return "\n".join(
        section(f"Changes in the last {arguments.days} days", lines, empty="no changes")
    )


def agent_proposals(
    db: Session, *, owner: User, arguments: Proposals, scope: PageScope, now: datetime
) -> str:
    """The agent's proposals, newest first."""
    query = select(AgentSuggestion).where(AgentSuggestion.owner_id == owner.id)
    if arguments.which == "open":
        query = query.where(AgentSuggestion.status.in_(OPEN_STATUSES))
    elif arguments.which == "answered":
        query = query.where(AgentSuggestion.status.not_in(OPEN_STATUSES))
    proposals = inside_rows(
        db,
        owner=owner,
        scope=scope,
        rows=query.order_by(AgentSuggestion.created_at.desc()),
        target=lambda row: (
            row.target_level,
            row.target_external_id,
            row.target_parent_id,
        ),
        limit=PROPOSAL_ROWS,
    )
    names = names_by_level(
        db,
        owner=owner,
        targets=[(row.target_level, row.target_external_id) for row in proposals],
    )
    accounts = subscribed_accounts(db, owner=owner)
    currency = accounts[0].currency if accounts else ""
    lines = [
        _proposal_line(
            row,
            name=names.get((row.target_level, row.target_external_id), ""),
            currency=currency,
        )
        for row in proposals
    ]
    return "\n".join(section("Agent proposals", lines, empty="no proposals"))


def open_problems(
    db: Session, *, owner: User, arguments: Nothing, scope: PageScope, now: datetime
) -> str:
    """The cabinet's own list of what is waiting, most urgent first."""
    from app.modules.notifications.selectors import cached_inbox

    items = cached_inbox(db, owner=owner, now=now)
    hidden = outside_targets(
        db,
        owner=owner,
        scope=scope,
        targets=[
            (item.subject.ref.level, item.subject.ref.id, "")
            for item in items
            if item.subject is not None
        ],
    )
    lines = [
        f"- [{item.level}] {item.title}: {item.body}"
        for item in items
        if item.subject is None
        or (item.subject.ref.level, item.subject.ref.id) not in hidden
    ][:PROBLEM_ROWS]
    return "\n".join(section("Waiting now", lines, empty="nothing is waiting"))


def _proposal_line(row: AgentSuggestion, *, name: str, currency: str) -> str:
    level = row.target_level
    line = (
        f"- {row.created_at:%Y-%m-%d}: {_label(SuggestionKind, row.kind)} "
        f"({RULE_LABELS.get(row.rule, row.rule)}) for {LEVEL_WORDS.get(level, level)} "
        f"{named(name, row.target_external_id)} - {_label(SuggestionStatus, row.status)}"
    )
    if row.cause:
        line += f", cause: {cause_label(row.cause)}"
    if row.reason:
        line += f", why: {trimmed(row.reason, NOTE_CHARS)}"
    if row.outcome:
        line += f", outcome: {_label(SuggestionOutcome, row.outcome)}"
        found = comparison(
            rule=row.rule,
            evidence=row.evidence,
            after=row.outcome_figures,
            currency=currency,
        )
        if found is not None:
            line += f" ({found.label}: {found.before} → {found.after})"
    return line


__all__ = ["agent_proposals", "open_problems", "recent_changes"]
