"""Which open proposals are about advertising built outside this product."""

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, Campaign
from app.modules.ads.selectors.launched import all_launched_campaign_ids
from app.modules.agent.models import AgentSuggestion


def built_elsewhere(db: Session, *, owner: User) -> ColumnElement[bool]:
    """The proposals whose campaign the mirror holds and we did not launch."""
    ours = list(all_launched_campaign_ids(db, owner=owner))
    theirs = select(Campaign.id).where(
        Campaign.owner_id == owner.id, Campaign.external_id.not_in(ours)
    )
    their_ids = select(Campaign.external_id).where(
        Campaign.owner_id == owner.id, Campaign.external_id.not_in(ours)
    )
    their_groups = select(AdSet.external_id).where(
        AdSet.owner_id == owner.id, AdSet.campaign_id.in_(theirs)
    )
    s = AgentSuggestion
    return or_(
        and_(s.target_level == "campaign", s.target_external_id.in_(their_ids)),
        and_(s.target_level == "adset", s.target_external_id.in_(their_groups)),
        and_(s.target_level == "ad", s.target_parent_id.in_(their_groups)),
    )


__all__ = ["built_elsewhere"]
