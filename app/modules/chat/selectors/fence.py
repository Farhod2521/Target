"""Which records name advertising on a page outside the subscription."""

from collections.abc import Callable, Iterable
from typing import Any, Final

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdSet
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.integrations.models import PageAccount
from app.modules.leads.models import LeadForm

Target = tuple[str, str, str]

BATCH: Final = 100


def inside_rows(
    db: Session,
    *,
    owner: User,
    scope: PageScope,
    rows: Select[Any],
    target: Callable[[Any], Target],
    limit: int,
) -> list[Any]:
    """The first ``limit`` of ``rows`` that name nothing outside, in order."""
    kept: list[Any] = []
    start = 0
    while len(kept) < limit:
        batch = list(db.scalars(rows.offset(start).limit(BATCH)))
        if not batch:
            break
        hidden = outside_targets(
            db, owner=owner, scope=scope, targets=[target(row) for row in batch]
        )
        kept += [row for row in batch if target(row)[:2] not in hidden]
        start += BATCH
    return kept[:limit]


def outside_targets(
    db: Session, *, owner: User, scope: PageScope, targets: Iterable[Target]
) -> set[tuple[str, str]]:
    """``{(level, id)}`` of the targets known to sit outside the subscription."""
    items = list(targets)
    groups = _groups_of(
        db,
        owner=owner,
        ads={each for level, each, parent in items if level == "ad" and not parent},
    )
    pages = _pages_of(
        db,
        owner=owner,
        forms={each for level, each, _parent in items if level == "form"},
    )
    return {
        (level, each)
        for level, each, parent in items
        if _hides(
            scope=scope,
            level=level,
            external_id=each,
            group=parent or groups.get(each, ""),
            page=pages.get(each, ""),
        )
    }


def _hides(
    *, scope: PageScope, level: str, external_id: str, group: str, page: str
) -> bool:
    if level == "form":
        return bool(page) and not scope.allows_page(page)
    return scope.hides(level=level, external_id=external_id, parent=group)


def _groups_of(db: Session, *, owner: User, ads: set[str]) -> dict[str, str]:
    if not ads:
        return {}
    return {
        str(ad): str(group)
        for ad, group in db.execute(
            select(Ad.external_id, AdSet.external_id)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .where(Ad.owner_id == owner.id, Ad.external_id.in_(ads))
        )
    }


def _pages_of(db: Session, *, owner: User, forms: set[str]) -> dict[str, str]:
    if not forms:
        return {}
    return {
        str(form): str(page or "")
        for form, page in db.execute(
            select(LeadForm.external_id, PageAccount.external_id)
            .outerjoin(PageAccount, PageAccount.id == LeadForm.page_id)
            .where(LeadForm.owner_id == owner.id, LeadForm.external_id.in_(forms))
        )
    }


__all__ = ["BATCH", "Target", "inside_rows", "outside_targets"]
