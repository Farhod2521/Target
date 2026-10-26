"""The groups this product switched on, as the watch reads them."""

from collections.abc import Collection, Iterable
from datetime import datetime
from typing import Any

from metaads.writing import is_dry_run_id
from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import Delivery, LaunchStatus, LaunchStep
from app.modules.ads.models import AdSet, CampaignLaunch
from app.modules.ads.selectors.launched import goal_campaign_ids
from app.modules.agent.selectors.running_watch import running_facts
from app.modules.agent.selectors.same_day import group_usuals, kind_of
from app.modules.agent.selectors.stopped_watch import stopped_rows
from app.modules.agent.selectors.suggestions import waiting
from app.modules.agent.selectors.watch_figures import (
    ad_states,
    group_facts,
    since_born,
    today_so_far,
)
from app.modules.agent.selectors.watched import Watched
from app.modules.agent.selectors.window import start_of
from app.modules.integrations.models import AdAccount
from core.agent.launch_watch import WATCH_HOURS, Watch, WatchedGroup, watch
from core.agent.running_watch import Running, running_watch
from core.metrics import Outcome

_LEFT_ALONE = frozenset({Delivery.PAUSED, Delivery.PAUSED_ABOVE, Delivery.FINISHED})


def watched_groups(
    db: Session,
    *,
    owner: User,
    accounts: Iterable[AdAccount],
    now: datetime,
    hidden_adsets: Collection[str] = (),
) -> list[Watched]:
    """Every running group launched here that something is due about."""
    asked = {
        suggestion.target_parent_id or suggestion.target_external_id
        for suggestion in waiting(db, owner=owner, now=now)
    }
    found: list[Watched] = []
    for account in accounts:
        born = switched_on(db, owner=owner, account=account)
        rows = (
            _rows(db, owner=owner, account=account, born=born, now=now) if born else []
        )
        found += [
            row
            for row in rows
            if row.adset_id not in hidden_adsets and row.adset_id not in asked
        ]
    return found


def watched_group(
    db: Session, *, owner: User, adset_id: str, now: datetime
) -> Watched | None:
    """One group, read the same way, for a button pressed about it."""
    launch = db.scalars(
        _recent(owner).where(
            cast(CampaignLaunch.created_refs, String).contains(adset_id)
        )
    ).first()
    if launch is None or launch.ad_account is None:
        return None
    born = switched_on(db, owner=owner, account=launch.ad_account)
    rows = _rows(db, owner=owner, account=launch.ad_account, born=born, now=now)
    return next((row for row in rows if row.adset_id == adset_id), None)


def _rows(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    born: dict[str, datetime],
    now: datetime,
) -> list[Watched]:
    """The running groups' lines, and the lines about groups the agent stopped."""
    ours = goal_campaign_ids(db, owner=owner)
    return [
        *_account_groups(
            db, owner=owner, account=account, born=born, ours=ours, now=now
        ),
        *stopped_rows(db, owner=owner, account=account, born=born, ours=ours, now=now),
    ]


def owners_with_launches(db: Session) -> set[Any]:
    """Which accounts have switched on anything built here."""
    return set(
        db.scalars(
            select(CampaignLaunch.owner_id)
            .where(
                CampaignLaunch.status == LaunchStatus.CREATED,
                CampaignLaunch.delivery_started_at.is_not(None),
            )
            .distinct()
        )
    )


def _recent(owner: User) -> Any:
    return select(CampaignLaunch).where(
        CampaignLaunch.owner_id == owner.id,
        CampaignLaunch.status == LaunchStatus.CREATED,
        CampaignLaunch.delivery_started_at.is_not(None),
    )


def switched_on(db: Session, *, owner: User, account: AdAccount) -> dict[str, datetime]:
    """``{group id: when it was switched on}`` for this account's launches."""
    born: dict[str, datetime] = {}
    for launch in db.scalars(
        _recent(owner).where(CampaignLaunch.ad_account_id == account.id)
    ):
        since = launch.delivery_started_at
        assert since is not None
        if launch.start_date is not None:
            since = max(since, start_of(launch.start_date, account.tzinfo()))
        for adset_id in ref_field.ref_ids(launch.created_refs, LaunchStep.ADSET):
            if not is_dry_run_id(adset_id):
                born[adset_id] = since
    return born


def _account_groups(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    born: dict[str, datetime],
    ours: Collection[str],
    now: datetime,
) -> list[Watched]:
    groups = list(
        db.scalars(
            select(AdSet).where(
                AdSet.owner_id == owner.id,
                AdSet.external_id.in_(list(born)),
                AdSet.delivery.not_in([str(state) for state in _LEFT_ALONE]),
            )
        )
    )
    if not groups:
        return []
    hours = {
        row.external_id: (now - born[row.external_id]).total_seconds() / 3600
        for row in groups
    }
    young = [row for row in groups if hours[row.external_id] < WATCH_HOURS]
    old = [row for row in groups if hours[row.external_id] >= WATCH_HOURS]
    figures = {
        **since_born(
            db, owner=owner, account=account, born=born, groups=young, now=now
        ),
        **today_so_far(db, owner=owner, account=account, groups=old, now=now),
    }
    running = running_facts(
        db, owner=owner, account=account, groups=old, born=born, now=now
    )
    ads = ad_states(db, owner=owner, adset_ids=[row.external_id for row in groups])
    usual = group_usuals(
        db, owner=owner, account=account, adset_ids=[row.external_id for row in young]
    )
    found: list[Watched] = []
    for row in groups:
        kind = kind_of(row.optimization_goal_raw, row.promoted_object_raw)
        group = group_facts(
            row=row,
            hours=hours[row.external_id],
            figures=figures.get(row.external_id, {}),
            kind=kind,
            ads=ads.get(row.external_id, set()),
            blocked=account.may_advertise is False,
            usual_cost_minor=usual(row.external_id, kind),
        )
        facts = running.get(row.external_id)
        due = watch(group) if facts is None else running_watch(group, facts)
        if group.blocked:
            due = None
        if due is not None:
            found.append(
                _watched(
                    row=row,
                    group=group,
                    kind=kind,
                    due=due,
                    account=account,
                    ours=ours,
                    running=facts,
                )
            )
    return found


def _watched(
    *,
    row: AdSet,
    group: WatchedGroup,
    kind: Outcome,
    due: Watch,
    account: AdAccount,
    ours: Collection[str],
    running: Running | None,
) -> Watched:
    campaign_id = row.campaign.external_id if row.campaign_id else ""
    return Watched(
        adset_id=row.external_id,
        name=row.name or row.external_id,
        campaign_id=campaign_id,
        delete_level="adset" if campaign_id in ours else "campaign",
        currency=account.currency,
        provider=account.provider,
        hours=int(group.hours),
        spend_minor=group.spend_minor,
        results=group.results,
        kind=kind,
        daily_budget_minor=group.daily_budget_minor,
        in_review=group.in_review,
        watch=due,
        running=running,
    )


__all__ = [
    "Watched",
    "owners_with_launches",
    "switched_on",
    "watched_group",
    "watched_groups",
]
