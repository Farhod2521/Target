from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import Campaign
from app.modules.ads.selectors.actions import latest_actions, still_running
from app.modules.ads.selectors.controls import controls_for
from app.modules.ads.selectors.early_touch import early_hours_on, young_launches
from app.modules.audit.constants import ActionType

__all__ = ["with_controls", "with_switches"]


def with_switches(
    db: Session, *, owner: User, campaigns: list[Campaign]
) -> list[Campaign]:
    watched = {
        campaign.external_id: [
            campaign.external_id,
            *(row.external_id for row in campaign.adsets),
        ]
        for campaign in campaigns
    }
    actions = latest_actions(
        db, owner=owner, external_ids=[row for ids in watched.values() for row in ids]
    )
    young = young_launches(db, owner=owner, now=utcnow())
    for campaign in campaigns:
        campaign.early_hours = early_hours_on(
            target=campaign, level=ManagedLevel.CAMPAIGN, young=young
        )
        for adset in campaign.adsets:
            adset.early_hours = early_hours_on(
                target=adset, level=ManagedLevel.ADSET, young=young
            )
        last = actions.get(campaign.external_id)
        campaign.controls = controls_for(target=campaign, level=ManagedLevel.CAMPAIGN)
        campaign.last_action = last
        campaign.pending = still_running(
            [actions.get(row) for row in watched[campaign.external_id]]
        )
        campaign.deleting = (
            last is not None
            and last.action == ActionType.DELETE_CAMPAIGN
            and still_running([last])
        )
    return campaigns


def with_controls(db: Session, *, owner: User, campaign: Campaign) -> Campaign:
    adsets = list(campaign.adsets)
    ads = [ad for adset in adsets for ad in adset.ads]
    actions = latest_actions(
        db,
        owner=owner,
        external_ids=[
            campaign.external_id,
            *(a.external_id for a in adsets),
            *(a.external_id for a in ads),
        ],
    )
    young = young_launches(db, owner=owner, now=utcnow())
    for row, at in (
        (campaign, ManagedLevel.CAMPAIGN),
        *((adset, ManagedLevel.ADSET) for adset in adsets),
        *((ad, ManagedLevel.AD) for ad in ads),
    ):
        row.early_hours = early_hours_on(target=row, level=at, young=young)
    campaign.controls = controls_for(target=campaign, level=ManagedLevel.CAMPAIGN)
    campaign.last_action = actions.get(campaign.external_id)
    for adset in adsets:
        adset.controls = controls_for(target=adset, level=ManagedLevel.ADSET)
        adset.last_action = actions.get(adset.external_id)
        adset.deleting = (
            adset.last_action is not None
            and adset.last_action.action == ActionType.DELETE_ADSET
            and still_running([adset.last_action])
        )
        adset.is_last = len(adsets) == 1
    for ad in ads:
        last = actions.get(ad.external_id)
        ad.controls = controls_for(target=ad, level=ManagedLevel.AD)
        ad.last_action = last
        ad.deleting = (
            last is not None
            and last.action == ActionType.DELETE_AD
            and still_running([last])
        )
        ad.is_last = len(ad.adset.ads) == 1
    return campaign
