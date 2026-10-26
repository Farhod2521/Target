"""The causes last night's diagnosis wrote, and the prices they carry."""

from collections.abc import Collection, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, Campaign
from app.modules.agent.models import AdSetDiagnosis
from app.modules.integrations.models import AdAccount


def usual_cost_of(row: AdSetDiagnosis, *, currency: str) -> int | None:
    """What one of this group's results usually costs, as last night read it."""
    evidence = row.evidence or {}
    if evidence.get("currency") != currency:
        return None
    value = evidence.get("account_cost_minor")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def usual_costs(
    db: Session, *, owner: User, adset_ids: Iterable[str], currency: str
) -> dict[str, int]:
    """``{group: its usual price}`` for these groups, from last night's rows."""
    ids = list(adset_ids)
    if not ids:
        return {}
    found: dict[str, int] = {}
    for row in db.scalars(
        select(AdSetDiagnosis).where(
            AdSetDiagnosis.owner_id == owner.id,
            AdSetDiagnosis.adset_external_id.in_(ids),
        )
    ):
        usual = usual_cost_of(row, currency=currency)
        if usual is not None:
            found[row.adset_external_id] = usual
    return found


def kind_usuals(
    db: Session, *, owner: User, account: AdAccount, hidden: Collection[str] = ()
) -> dict[str, int]:
    """``{kind of result: its usual price}`` on this account, from last night."""
    ids = select(AdSet.external_id).where(
        AdSet.owner_id == owner.id,
        AdSet.campaign_id.in_(
            select(Campaign.id).where(Campaign.ad_account_id == account.id)
        ),
        AdSet.external_id.not_in(list(hidden)),
    )
    found: dict[str, tuple[int, int]] = {}
    for row in db.scalars(
        select(AdSetDiagnosis).where(
            AdSetDiagnosis.owner_id == owner.id,
            AdSetDiagnosis.adset_external_id.in_(ids),
        )
    ):
        usual = usual_cost_of(row, currency=account.currency)
        kind = (row.evidence or {}).get("outcome")
        if usual is None or not isinstance(kind, str):
            continue
        spent = (row.evidence or {}).get("spend_minor")
        spent = spent if isinstance(spent, int) else 0
        if kind not in found or spent > found[kind][0]:
            found[kind] = (spent, usual)
    return {kind: usual for kind, (_spent, usual) in found.items()}


__all__ = ["kind_usuals", "usual_cost_of", "usual_costs"]
