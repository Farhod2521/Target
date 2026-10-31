"""What a launch's ad groups are, before any of them exists at the provider."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ads import groups as group_field
from app.modules.ads.models import CampaignLaunch, LaunchCreative
from app.modules.ads.naming import adset_name
from app.modules.ads.selectors.budget_level import held_by_campaign
from app.modules.ads.selectors.variants import launch_variants
from app.modules.businesses.models import Business


@dataclass(frozen=True, slots=True)
class GroupCard:
    """One ad group: what it is called, what it costs, what is in it."""

    position: int
    name: str
    named: bool
    daily_budget_minor: int
    variants: tuple[LaunchCreative, ...]

    @property
    def size(self) -> int:
        return len(self.variants)

    @property
    def label(self) -> str:
        return self.name or f"{self.position + 1}-guruh"

    @property
    def short_label(self) -> str:
        if self.named:
            return self.name
        return self.name.rsplit(" · ", 1)[-1] if self.name else self.label

    @property
    def budget_each_minor(self) -> int:
        return self.daily_budget_minor // self.size if self.size else 0


@dataclass(frozen=True, slots=True)
class Arrangement:
    """Every group of one launch, in order, and where it came from."""

    groups: tuple[GroupCard, ...]
    arranged: bool

    @property
    def ad_count(self) -> int:
        return sum(group.size for group in self.groups)

    @property
    def total_budget_minor(self) -> int:
        return sum(group.daily_budget_minor for group in self.groups)

    @property
    def is_split(self) -> bool:
        return len(self.groups) > 1

    @property
    def filled(self) -> tuple[GroupCard, ...]:
        return tuple(group for group in self.groups if group.size)


def arrangement(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business | None = None,
    variants: list[LaunchCreative] | None = None,
) -> Arrangement:
    """How this launch's adverts are spread over groups, right now."""
    rows = launch_variants(db, launch=launch) if variants is None else list(variants)
    stored = list(launch.ad_groups or [])
    if stored:
        return _as_arranged(launch=launch, business=business, rows=rows, stored=stored)
    return _as_default(launch=launch, business=business, rows=rows)


def underfunded(
    db: Session,
    *,
    launch: CampaignLaunch,
    floor_minor: int,
    variants: list[LaunchCreative] | None = None,
) -> GroupCard | None:
    """The first group this launch would build on less than ``floor_minor``."""
    if floor_minor <= 0 or held_by_campaign(launch=launch):
        return None
    for group in arrangement(db, launch=launch, variants=variants).filled:
        if group.daily_budget_minor < floor_minor:
            return group
    return None


def _as_arranged(
    *,
    launch: CampaignLaunch,
    business: Business | None,
    rows: list[LaunchCreative],
    stored: list[Any],
) -> Arrangement:
    saved = group_field.read(stored)
    buckets: list[list[LaunchCreative]] = [[] for _unused in saved]
    last = len(saved) - 1
    for row in rows:
        buckets[min(max(row.group, 0), last)].append(row)
    return Arrangement(
        groups=tuple(
            GroupCard(
                position=index,
                name=str(item.get(group_field.NAME) or "")
                or _generated(
                    launch=launch, business=business, index=index, of=len(saved)
                ),
                named=bool(item.get(group_field.NAME)),
                daily_budget_minor=int(item.get(group_field.BUDGET) or 0),
                variants=tuple(buckets[index]),
            )
            for index, item in enumerate(saved)
        ),
        arranged=True,
    )


def _as_default(
    *, launch: CampaignLaunch, business: Business | None, rows: list[LaunchCreative]
) -> Arrangement:
    return Arrangement(
        groups=(
            GroupCard(
                position=0,
                name=_generated(launch=launch, business=business, index=0, of=1),
                named=False,
                daily_budget_minor=int(launch.daily_budget_minor or 0),
                variants=tuple(rows),
            ),
        ),
        arranged=False,
    )


def _generated(
    *, launch: CampaignLaunch, business: Business | None, index: int, of: int
) -> str:
    if business is None:
        return ""
    return adset_name(launch=launch, business=business, position=index, of=of)
