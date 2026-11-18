"""What the half-hourly guard told the owner, and what it stopped.

On prod a client asked «nega reklamam to'xtadi?» and the assistant saw only
«stopped by the agent» in the changes: the guard's reason - the price ten
times the group's usual, three days with nothing back - was in its own table
and nobody read it. These are the same words the owner got in the cabinet's
list and on Telegram (``agent.guard_copy``), with when, and what they
answered.
"""

from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope

ROWS: Final = 12


def guard_alerts(
    db: Session, *, owner: User, scope: PageScope, days: int, now: datetime
) -> str:
    from app.modules.agent.guard_copy import (
        button_label,
        guard_advice,
        guard_body,
        guard_place,
        guard_title,
    )
    from app.modules.agent.models import GuardAlert

    since = now - timedelta(days=max(1, days))
    rows = [
        row
        for row in db.scalars(
            select(GuardAlert)
            .where(
                GuardAlert.owner_id == owner.id,
                or_(GuardAlert.updated_at >= since, GuardAlert.closed_at.is_(None)),
            )
            .order_by(GuardAlert.updated_at.desc())
        )
        if not row.campaign_external_id
        or scope.allows_campaign(row.campaign_external_id)
    ][:ROWS]
    head = (
        f"## What the guard found over the last {days} days (it checks every "
        "running group every half hour)"
    )
    if not rows:
        return (
            f"{head}\n- nothing: it warned about nothing and stopped nothing in "
            "this window. A stop that is not here was made by the owner, the "
            "agent's night run or in Ads Manager - `recent_changes` says which."
        )
    lines = [head]
    for row in rows:
        place = " · ".join(f"{label}: «{name}»" for label, name in guard_place(row))
        stopped = row.action == "stop"
        lines.append(
            f"- {row.updated_at:%Y-%m-%d %H:%M} UTC · "
            f"{'STOPPED' if stopped else 'warning'} · {place}"
        )
        lines.append(f"  - title: {guard_title(row)}")
        body = " ".join(line for line in guard_body(row).splitlines() if line)
        if body:
            lines.append(f"  - words: {body}")
        if row.answer:
            when = (
                f" on {row.answered_at:%Y-%m-%d %H:%M} UTC" if row.answered_at else ""
            )
            lines.append(
                f"  - the owner pressed «{_label(button_label, row.answer)}»{when}"
            )
        elif row.closed_at is None and not stopped:
            lines.append(f"  - not answered yet; {guard_advice(row)}")
        told = (
            f"cabinet list and Telegram ({row.telegram_sent_at:%Y-%m-%d %H:%M} UTC)"
            if row.telegram_sent_at
            else "cabinet list"
        )
        state = (
            f"over since {row.closed_at:%Y-%m-%d %H:%M} UTC"
            if row.closed_at
            else "still open"
        )
        lines.append(f"  - told in: {told}; {state}")
    return "\n".join(lines)


def _label(label_of, answer: str) -> str:  # type: ignore[no-untyped-def]
    try:
        return str(label_of(answer))
    except KeyError:
        return answer


__all__ = ["guard_alerts"]
