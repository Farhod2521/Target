"""What the owner's CRM did with each campaign's leads.

On prod the assistant answered «sales are low» and «poor-quality callers»
with «the platform cannot see sales» - while the product's own CRM keeps,
for every lead, whether it was sold, refused, or marked poor quality, and
why. Counted per campaign over the leads that arrived in the window, the
same cohort the CRM's Statistika uses. Counts only: never a name or phone.
"""

import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.crm.constants import STAGE_KIND_LABELS, StageKind
from app.modules.leads.constants import MANUAL_PROVIDER

CAMPAIGN_ROWS: Final = 12
REASON_ROWS: Final = 3
# Fewer closed leads than this and a share is not worth saying.
FEW_CLOSED: Final = 5


def crm_outcomes(
    db: Session, *, owner: User, scope: PageScope, days: int, now: datetime
) -> str:
    from app.modules.ads.models import Campaign
    from app.modules.chat.selectors.lookups.common import money, window
    from app.modules.chat.selectors.scope import lead_window
    from app.modules.crm.models import CrmCard, CrmStage
    from app.modules.leads.models import Lead

    since, until = window(db, owner=owner, days=days)
    start, end = lead_window(db, owner=owner, since=since, until=until)
    rows = db.execute(
        select(
            Lead.campaign_external_id,
            CrmStage.kind,
            CrmCard.lost_reason_name,
            CrmCard.won_amount_minor,
            CrmCard.currency,
        )
        .join(CrmCard, CrmCard.lead_id == Lead.id)
        .join(CrmStage, CrmStage.id == CrmCard.stage_id)
        .where(
            Lead.owner_id == owner.id,
            Lead.is_test.is_(False),
            # Advert leads only: a customer typed onto the board by hand is
            # no campaign's outcome.
            Lead.provider != MANUAL_PROVIDER,
            Lead.received_at >= start,
            Lead.received_at <= end,
        )
    ).all()
    head = f"## CRM outcomes of leads that arrived {since} to {until}"
    if not rows:
        return (
            f"{head}\n- no lead of this window is in the CRM. Sales are not "
            "known here: leads from chat or call campaigns are not CRM cards, "
            "and the CRM is filled only when the owner or their managers move "
            "cards on the CRM screen."
        )
    kinds: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    won: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for campaign_id, kind, reason, amount, currency in rows:
        key = campaign_id or ""
        if key and not scope.allows_campaign(key):
            continue
        kinds[key][kind] += 1
        if kind in (StageKind.LOST, StageKind.JUNK) and reason:
            reasons[key][reason] += 1
        if kind == StageKind.WON and amount:
            won[key][currency or ""] += int(amount)
    names = {
        row.external_id: row.name
        for row in db.execute(
            select(Campaign.external_id, Campaign.name).where(
                Campaign.owner_id == owner.id,
                Campaign.external_id.in_([key for key in kinds if key]),
            )
        )
    }
    order = sorted(kinds, key=lambda key: -sum(kinds[key].values()))
    lines = [head]
    for key in order[:CAMPAIGN_ROWS]:
        tally = kinds[key]
        total = sum(tally.values())
        name = f"«{names.get(key) or key}»" if key else "leads with no campaign"
        parts = [f"leads {total}"] + [
            f"{STAGE_KIND_LABELS[kind]} {tally[kind]}"
            for kind in StageKind
            if tally[kind]
        ]
        closed = sum(
            tally[kind] for kind in (StageKind.WON, StageKind.LOST, StageKind.JUNK)
        )
        if closed >= FEW_CLOSED:
            parts.append(
                f"sold {tally[StageKind.WON] * 100 // closed}% of those closed"
            )
        for currency, amount in won[key].items():
            parts.append(f"sold for {money(amount, currency)}")
        lines.append(f"- {name}: " + ", ".join(parts))
        top = reasons[key].most_common(REASON_ROWS)
        if top:
            lines.append(
                "  - why refused or poor: "
                + "; ".join(f"{reason} {count}" for reason, count in top)
            )
    untouched = sum(kinds[key][StageKind.NEW] for key in kinds)
    if untouched:
        lines.append(
            f"- {untouched} lead(s) still in «{STAGE_KIND_LABELS[StageKind.NEW]}»: "
            "nobody moved them, so their outcome is not known."
        )
    lines += _managers(db, owner=owner, scope=scope, start=start, end=end, now=now)
    return "\n".join(lines)


def _managers(
    db: Session,
    *,
    owner: User,
    scope: PageScope,
    start: datetime,
    end: datetime,
    now: datetime,
) -> list[str]:
    """Who has the leads of the window, and what each did with them: given,
    untouched, sold, refused, poor, overdue, and their last move in the CRM."""
    from sqlalchemy import func

    from app.modules.crm.models import CrmActivity, CrmCard, CrmMember, CrmStage
    from app.modules.leads.models import Lead

    rows = db.execute(
        select(
            CrmCard.assignee_id,
            CrmStage.kind,
            CrmCard.due_at,
            CrmCard.closed_at,
            Lead.campaign_external_id,
        )
        .join(Lead, Lead.id == CrmCard.lead_id)
        .join(CrmStage, CrmStage.id == CrmCard.stage_id)
        .where(
            CrmCard.owner_id == owner.id,
            Lead.is_test.is_(False),
            Lead.provider != MANUAL_PROVIDER,
            Lead.received_at >= start,
            Lead.received_at <= end,
        )
    ).all()
    members = list(db.scalars(select(CrmMember).where(CrmMember.owner_id == owner.id)))
    if not rows and not members:
        return []
    tally: dict[uuid.UUID | None, Counter[str]] = defaultdict(Counter)
    for assignee, kind, due_at, closed_at, campaign_id in rows:
        if campaign_id and not scope.allows_campaign(campaign_id):
            continue
        tally[assignee][kind] += 1
        tally[assignee]["given"] += 1
        if due_at is not None and closed_at is None and due_at < now:
            tally[assignee]["overdue"] += 1
    people = {member.user_id: member for member in members}
    ids = [key for key in tally if key is not None] + [
        key for key in people if key not in tally
    ]
    last = (
        dict(
            db.execute(
                select(CrmActivity.actor_id, func.max(CrmActivity.created_at))
                .where(CrmActivity.owner_id == owner.id, CrmActivity.actor_id.in_(ids))
                .group_by(CrmActivity.actor_id)
            ).all()
        )
        if ids
        else {}
    )
    names = (
        {
            row.id: row.full_name or row.email
            for row in db.scalars(select(User).where(User.id.in_(ids)))
        }
        if ids
        else {}
    )
    lines = ["", "## Who works these leads in the CRM"]
    for key in ids[:CAMPAIGN_ROWS]:
        counts = tally.get(key, Counter())
        if key == owner.id:
            who = "the owner themselves"
        else:
            member = people.get(key)
            state = ""
            if member is not None and not member.is_active:
                state = " (switched off)"
            elif member is not None and not member.takes_leads:
                state = " (takes no new leads)"
            who = f"manager «{names.get(key, 'unknown')}»{state}"
        parts = [f"given {counts['given']}"] + [
            f"{STAGE_KIND_LABELS[kind]} {counts[kind]}"
            for kind in StageKind
            if counts[kind]
        ]
        if counts["overdue"]:
            parts.append(f"past their «muddat» {counts['overdue']}")
        moved = last.get(key)
        parts.append(
            f"last move in the CRM {moved:%Y-%m-%d %H:%M} UTC"
            if moved
            else "no move in the CRM yet"
        )
        lines.append(f"- {who}: " + ", ".join(parts))
    loose = tally.get(None)
    if loose:
        lines.append(
            f"- given to nobody: {loose['given']} lead(s) - they wait on the "
            "CRM for someone to take them."
        )
    return lines


__all__ = ["crm_outcomes"]
