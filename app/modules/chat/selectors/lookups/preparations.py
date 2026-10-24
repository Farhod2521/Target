"""What this product was building, and what became of it."""

from datetime import datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import LaunchStatus, LaunchStep
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.lookups.common import named, section, trimmed, window
from core.chat.lookup_arguments import Window
from core.chat.lookups import PREPARATION_ROWS
from core.chat.preparations import trouble_of

NAME_CHARS = 60

SETTLED = frozenset(
    {LaunchStatus.CREATED, LaunchStatus.FAILED, LaunchStatus.ROLLED_BACK}
)


def preparations(
    db: Session, *, owner: User, arguments: Window, scope: PageScope, now: datetime
) -> str:
    """Campaigns being prepared on this page, newest first."""
    from datetime import UTC

    since, until = window(db, owner=owner, days=arguments.days)
    rows = db.scalars(
        select(CampaignLaunch)
        .where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.created_at >= datetime.combine(since, time.min, tzinfo=UTC),
            CampaignLaunch.created_at <= datetime.combine(until, time.max, tzinfo=UTC),
        )
        .order_by(CampaignLaunch.created_at.desc())
        .limit(PREPARATION_ROWS + 1)
    )
    mine = [row for row in rows if _on_this_page(row, scope=scope)]
    lines = [_line(row) for row in mine[:PREPARATION_ROWS]]
    out = section(
        f"Campaigns prepared here, {since} to {until}",
        lines,
        empty="none were started in this window",
    )
    if len(mine) > PREPARATION_ROWS:
        out.append(f"- and {len(mine) - PREPARATION_ROWS} older ones")
    return "\n".join(out)


def _on_this_page(launch: CampaignLaunch, *, scope: PageScope) -> bool:
    page = launch.page.external_id if launch.page is not None else ""
    if page:
        return page == scope.current or (not scope.current and page in scope.pages)
    return len(scope.pages) == 1


def _label(choices: type, value: str) -> str:
    try:
        return str(choices(value).label)
    except ValueError:
        return value


def _line(launch: CampaignLaunch) -> str:
    """One preparation: what it was, how far it got, and what stopped it."""
    parts = [
        f"- {named(_name(launch), str(launch.id)[:8])}",
        f"status {_label(LaunchStatus, launch.status)}",
        f"started {launch.created_at.date()}",
    ]
    if launch.status not in SETTLED and launch.step:
        parts.append(f"reached {_label(LaunchStep, launch.step)}")
    if launch.status in (LaunchStatus.FAILED, LaunchStatus.ROLLED_BACK):
        parts.append(
            trouble_of(launch.error_code, provider_said=_provider_said(launch))
        )
    elif launch.status == LaunchStatus.CREATED:
        parts.append(
            "switched on" if launch.delivery_started_at else _not_started(launch)
        )
    return ", ".join(parts)


def _name(launch: CampaignLaunch) -> str:
    answers = launch.answers if isinstance(launch.answers, dict) else {}
    for key in ("offer_text", "offer", "goal"):
        value = answers.get(key)
        if isinstance(value, str) and value.strip():
            return trimmed(value, NAME_CHARS)
    return ""


def _not_started(launch: CampaignLaunch) -> str:
    note = trimmed(launch.delivery_note, NAME_CHARS * 2)
    return (
        f"created but not switched on ({note})" if note else "created, not switched on"
    )


def _provider_said(launch: CampaignLaunch) -> str:
    detail = launch.error_detail if isinstance(launch.error_detail, dict) else {}
    said = detail.get("message") or detail.get("title") or ""
    return str(said) if isinstance(said, str) else ""


__all__ = ["preparations"]
