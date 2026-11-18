"""The half-hourly guard: write what today's figures say, and stop what must stop.

Rules only - see :mod:`core.agent.guard`. Each pass reads every running
group of the owner's accounts whose figures are fresh, and keeps one open
row a group and kind:

- a new finding opens a row; a finding gone further - a price at the next
  step - moves the row's step, and that is what a second message waits for;
- a price rise closes when the price eases, and at the end of its day -
  tomorrow's price starts again from its first step; the other warnings close on a
  later day than they were raised, so a figure hovering at its bar is said
  once a day at most and not every half hour;
- a warning closed and found again the same day - a price back over its
  bar, a group missing from one reading - opens a new row but no new
  message at a step the owner was already told that day, and keeps the
  answer they gave it;
- «leave it for now» holds a stop back for three days from the answer: the
  finding stays a warning, and only a page that does not open still stops;
- a stop pauses the group at the provider, as the agent, and keeps the
  day's figures on the row: switched back on the same day, the group is
  counted from there.

Nothing here sends a message: the rows are what the notices are written from.
"""

import logging
from collections.abc import Mapping
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.ads import actions
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.services.manage import FOR_ADSET, Origin, switch_of
from app.modules.agent.constants import GUARD_STOP_MARK
from app.modules.agent.models import GuardAlert
from app.modules.agent.selectors.guard import (
    COUNTED,
    Guarded,
    fresh,
    guarded_groups,
)
from app.modules.audit.constants import ActionStatus, ActionType, ActorType
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import AdAccount
from core.agent.guard import Finding, eased, judge

logger = logging.getLogger(__name__)
BY_ITSELF = Origin(actor_type=ActorType.AGENT)
STOP = "stop"
WARN = "warn"
PRICE = "price"
SITE_DOWN = "site_down"
LEAVE = "leave"
# How long «leave it for now» holds the guard's own stop back.
LEAVE_HOLDS = timedelta(hours=72)


def run_guard(db: Session, *, owner: User, now: datetime, may_stop: bool = True) -> int:
    """One owner's pass. Returns how many rows were opened or moved. Commits.

    ``may_stop`` is off for an owner who switched the agent off: every
    finding is then a warning, and the stop is theirs to press.
    """
    from app.modules.integrations.selectors.slots import enabled_ad_accounts

    changed = 0
    for account in enabled_ad_accounts(db, owner=owner):
        if fresh(db, owner=owner, account=account, now=now):
            changed += _account(
                db, owner=owner, account=account, now=now, may_stop=may_stop
            )
    return changed


def _account(
    db: Session, *, owner: User, account: AdAccount, now: datetime, may_stop: bool
) -> int:
    rows = list(
        db.scalars(
            select(GuardAlert)
            .where(
                GuardAlert.owner_id == owner.id,
                GuardAlert.ad_account_id == account.id,
            )
            .order_by(GuardAlert.created_at.desc())
        )
    )
    guarded = guarded_groups(
        db, owner=owner, account=account, now=now, baselines=_baselines(rows)
    )
    by_group = {item.group.adset_id: item for item in guarded}
    pausing = _being_paused(db, owner=owner, adset_ids=list(by_group))
    told = _told_today(rows, clock=account.tzinfo(), now=now)
    _close_yesterdays_prices(
        rows, today=now.astimezone(account.tzinfo()).date(), now=now
    )
    findings: dict[tuple[str, str], tuple[Finding, Guarded]] = {}
    for item in guarded:
        if item.group.adset_id in pausing:
            continue
        for finding in judge(item.group):
            findings[finding.ad_id or finding.adset_id, finding.kind] = (finding, item)
    open_rows = {
        (row.external_id, row.kind): row for row in rows if row.closed_at is None
    }
    for key, row in open_rows.items():
        if row.adset_external_id in pausing:
            # The mirror says it runs until the stop lands: not over yet.
            continue
        if key not in findings and _over(row, by_group=by_group, now=now):
            row.closed_at = now
    db.flush()
    changed = 0
    for key, (finding, item) in findings.items():
        current = open_rows.get(key)
        if current is not None and current.closed_at is not None:
            current = None
        changed += _one(
            db,
            owner=owner,
            item=item,
            finding=finding,
            row=current,
            now=now,
            may_stop=may_stop,
            told=told.get(key),
        )
    db.commit()
    return changed


def _close_yesterdays_prices(
    rows: list[GuardAlert], *, today: date, now: datetime
) -> None:
    """A price warning is about its own day. Left open overnight, today's
    first result - one lead, an hour in - would read as the rise going a
    step further; closed, today's price is judged from its own first step."""
    for row in rows:
        if row.closed_at is not None or row.kind != PRICE or row.action == STOP:
            continue
        day = (row.figures or {}).get("day") or ""
        if day and day < today.isoformat():
            row.closed_at = now


def _told_today(
    rows: list[GuardAlert], *, clock: tzinfo, now: datetime
) -> dict[tuple[str, str], GuardAlert]:
    """``{(object, kind): the closed warning of today told furthest}``.

    Only today's - by the day it was raised, in the account's clock - so a
    warning still true tomorrow is said again tomorrow, once."""
    today: date = now.astimezone(clock).date()
    found: dict[tuple[str, str], GuardAlert] = {}
    for row in rows:
        if row.closed_at is None or row.action == STOP or row.said_step <= 0:
            continue
        if row.created_at.astimezone(clock).date() != today:
            continue
        key = (row.external_id, row.kind)
        if key not in found or row.said_step > found[key].said_step:
            found[key] = row
    return found


def _baselines(rows: list[GuardAlert]) -> dict[str, Mapping[str, Any]]:
    """Each group's newest figures at a stop - newest first, as ``rows`` are."""
    found: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if row.baseline and row.adset_external_id not in found:
            found[row.adset_external_id] = row.baseline
    return found


def _being_paused(db: Session, *, owner: User, adset_ids: list[str]) -> set[str]:
    """Groups a stop is already on its way to: the mirror still says they
    run, and a second request would only be refused."""
    if not adset_ids:
        return set()
    rows = db.execute(
        select(ActionLog.target_external_id, ActionLog.request_payload).where(
            ActionLog.owner_id == owner.id,
            ActionLog.action == str(ActionType.PAUSE),
            or_(
                and_(
                    ActionLog.target_level == ManagedLevel.ADSET,
                    ActionLog.target_external_id.in_(adset_ids),
                ),
                # A campaign's one group is stopped on its campaign.
                and_(
                    ActionLog.target_level == ManagedLevel.CAMPAIGN,
                    ActionLog.request_payload[FOR_ADSET].as_string().in_(adset_ids),
                ),
            ),
            ActionLog.status == ActionStatus.PENDING,
        )
    )
    return {
        str((payload or {}).get(FOR_ADSET) or external_id)
        for external_id, payload in rows
    }


def _over(row: GuardAlert, *, by_group: Mapping[str, Guarded], now: datetime) -> bool:
    """Whether an open row with no finding this pass has ended."""
    item = by_group.get(row.adset_external_id)
    if row.action == STOP:
        # Stopped by us: it stays said until the group runs again.
        return item is not None
    if item is None:
        # No longer running: nothing left to warn about.
        return True
    if row.kind == PRICE:
        return eased(item.group)
    return row.created_at.astimezone(item.account.tzinfo()).date() < item.day


def _one(
    db: Session,
    *,
    owner: User,
    item: Guarded,
    finding: Finding,
    row: GuardAlert | None,
    now: datetime,
    may_stop: bool,
    told: GuardAlert | None = None,
) -> int:
    """Open a row, move it a step, or leave it. Returns 1 when something changed.

    ``told`` is today's closed warning on the same thing: a new row at a step
    it already said is written down, but not said again."""
    held = _held(row, now=now) or _held(told, now=now)
    stops = (
        finding.action == STOP and may_stop and (finding.kind == SITE_DOWN or not held)
    )
    if (
        row is not None
        and finding.step <= row.step
        and not (stops and _now_stops(row, finding))
    ):
        return 0
    action = finding.action
    advice = finding.advice
    if action == STOP and not stops:
        action, advice = WARN, "pause"
    if action == STOP and finding.kind == SITE_DOWN and not _still_down(item):
        return 0
    log_id = None
    if action == STOP:
        try:
            with db.begin_nested():
                log_id = _stop(db, owner=owner, item=item, finding=finding)
        except DomainError as exc:
            logger.info(
                "guard_stop_refused",
                extra={"adset": finding.adset_id, "why": type(exc).__name__},
            )
            action, advice = WARN, "pause"
    if row is None:
        row = GuardAlert(
            owner_id=owner.id,
            provider=item.account.provider,
            ad_account_id=item.account.id,
            level="ad" if finding.ad_id else "adset",
            external_id=finding.ad_id or finding.adset_id,
            adset_external_id=finding.adset_id,
            campaign_external_id=item.campaign_external_id,
            kind=finding.kind,
            created_at=now,
        )
        db.add(row)
    # A new step is a new question: the answer given to the last one - «leave
    # it for now», a lower budget - does not answer this one. A stop that
    # «leave» held back is the exception: the answer is what holds it, and it
    # is kept, off the list and unsaid, until it runs out.
    kept = (row.answer, row.answered_at) if _held(row, now=now) else None
    row.answer, row.answered_at = "", None
    if kept is not None and finding.action == STOP and action != STOP:
        row.answer, row.answered_at = kept
        row.said_step = finding.step
    row.name = _name(item, finding)
    row.action = action
    row.advice = advice
    row.step = finding.step
    row.times = finding.times
    row.result_kind = item.kind
    row.currency = item.currency
    row.figures = _figures(item, finding) | {
        "sole_group": switch_of(
            db, user=owner, level=ManagedLevel.ADSET, external_id=finding.adset_id
        )[0]
        == ManagedLevel.CAMPAIGN
    }
    if action != STOP and told is not None and told.said_step >= row.step:
        row.said_step = max(row.said_step or 0, told.said_step)
        # «Leave it for now» still answers the same step; a closing answer
        # ended that row and is not carried.
        if told.answer == "leave":
            row.answer, row.answered_at = told.answer, told.answered_at
    if log_id is not None:
        # A stop is always said, at a step already said as a warning too.
        row.said_step = min(row.said_step or 0, row.step - 1)
        row.action_log_id = log_id
        row.baseline = {
            "day": item.day.isoformat(),
            **{name: getattr(item.group, name) for name in COUNTED},
        }
    db.flush()
    return 1


def _held(row: GuardAlert | None, *, now: datetime) -> bool:
    """Whether the owner said «leave it for now» to this, not long ago."""
    if row is None or row.answer != LEAVE or row.answered_at is None:
        return False
    return now - row.answered_at < LEAVE_HOLDS


def _now_stops(row: GuardAlert, finding: Finding) -> bool:
    """A warning whose finding has become a stop at the same step."""
    return row.action != STOP and finding.action == STOP


def _still_down(item: Guarded) -> bool:
    """Look at the page once more before stopping for it: the stored look
    may be an hour old, and one bad minute must not stop an advert."""
    from app.modules.ads.services.preflight import look_at_site

    return any(look_at_site(url=url).is_down for url in item.down_urls)


def _stop(db: Session, *, owner: User, item: Guarded, finding: Finding) -> Any:
    """The pause, marked as the guard's in the same transaction as the request."""
    log = actions.request(
        db,
        user=owner,
        ask=actions.Pause(level=ManagedLevel.ADSET, external_id=finding.adset_id),
        origin=BY_ITSELF,
    )
    log.request_payload = {
        **(log.request_payload or {}),
        GUARD_STOP_MARK: {"kind": finding.kind, "times": finding.times},
    }
    log.reason = f"guard:{finding.kind}"
    db.flush()
    return log.id


def _name(item: Guarded, finding: Finding) -> str:
    if finding.ad_id:
        for advert in item.group.ads:
            if advert.ad_id == finding.ad_id and advert.name:
                return advert.name
    return item.name


def _figures(item: Guarded, finding: Finding) -> dict[str, Any]:
    """What the message is written from, as it stood when the step was reached."""
    group = item.group
    spend, results = group.spend_minor, group.results
    if finding.ad_id:
        for advert in group.ads:
            if advert.ad_id == finding.ad_id:
                spend, results = advert.spend_minor, advert.results
    return {
        "day": item.day.isoformat(),
        "spend_minor": spend,
        "results": results,
        "group_spend_minor": group.spend_minor,
        "dry_spend_minor": group.dry_spend_minor,
        "dry_days": group.dry_days,
        "impressions": group.impressions,
        "link_clicks": group.link_clicks,
        "frequency": group.frequency,
        "usual_cost_minor": group.usual.cost_minor,
        "usual_link_ctr_bp": group.usual.link_ctr_bp,
        "usual_cpm_minor": group.usual.cpm_minor,
        "usual_source": group.usual.source,
        "causes": list(finding.causes),
        "group_name": item.name,
        "campaign_name": item.campaign_name,
        "page_name": item.page_name,
        "learning": group.learning,
        "ours": group.ours,
        "own_budget": group.own_budget,
        "day_budget_minor": group.day_budget_minor,
        "past_results": group.past_results,
        "hours_running": (
            int(group.hours_running) if group.hours_running is not None else None
        ),
    }


__all__ = ["run_guard"]
