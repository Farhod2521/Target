"""Why a campaign that says «Ishlayapti» has shown nothing.

On prod the assistant met three such campaigns in one day - one at 50 USD a
day, one 94 hours after it was switched on - and each time said «I do not
know why». The agent's diagnosis reads a group with no impressions as «too
early», which is right for an hour and wrong for four days. This reads what
the mirror already holds about each level and names what stands in the way;
when nothing does, it says so, so the model prepares a request instead of
guessing.
"""

from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.chat.selectors.lookups.common import money

# Less than this since it was made, no impressions is normal.
QUIET_HOURS: Final = 6
# Meta says it reviews within a day; longer than this is worth naming.
LONG_REVIEW: Final = timedelta(hours=24)
# Meta's effective statuses that hold delivery, in words for the model.
HELD: Final[dict[str, str]] = {
    "PENDING_REVIEW": "waits for Meta's review",
    "IN_PROCESS": "is being processed by Meta",
    "DISAPPROVED": "was refused by Meta",
    "WITH_ISSUES": "has an issue Meta reported",
    "PENDING_BILLING_INFO": "waits for a payment method on the ad account",
    "CAMPAIGN_PAUSED": "is held by its paused campaign",
    "ADSET_PAUSED": "is held by its paused ad group",
    "PAUSED": "is switched off",
    "ARCHIVED": "is archived",
    "DELETED": "is deleted",
}


def stalled_lines(
    db: Session, *, owner: User, campaign: Campaign, shown: int, now: datetime
) -> list[str]:
    """A section when the campaign runs and shows nothing; else nothing."""
    if campaign.delivery != Delivery.ACTIVE or shown > 0:
        return []
    made = campaign.created_time or campaign.created_at
    if made is None or now - made < timedelta(hours=QUIET_HOURS):
        return []
    hours = int((now - made).total_seconds() // 3600)
    found = [
        *_groups(db, owner=owner, campaign=campaign, now=now),
        *_adverts(db, owner=owner, campaign=campaign, now=now),
        *_account(campaign),
    ]
    head = (
        f"## Shown 0 times although it runs - made {hours} hours ago. What "
        "the product can see in the way:"
    )
    if not found:
        found = [
            "- nothing: every level is on, nothing waits for review, the ad "
            "account can advertise. The product cannot see the cause - say "
            "so and prepare a request for Support; do not guess."
        ]
    return ["", head, *found]


def _groups(
    db: Session, *, owner: User, campaign: Campaign, now: datetime
) -> list[str]:
    lines: list[str] = []
    groups = list(
        db.scalars(
            select(AdSet).where(
                AdSet.owner_id == owner.id, AdSet.campaign_id == campaign.id
            )
        )
    )
    if not groups:
        return ["- it has no ad groups mirrored"]
    live = [row for row in groups if row.delivery == Delivery.ACTIVE]
    if not live:
        lines.append("- none of its ad groups is running")
    minimum = int(campaign.ad_account.min_daily_budget_minor or 0)
    for row in groups:
        name = f"ad group «{row.name or row.external_id}»"
        if row.start_time is not None and row.start_time > now:
            lines.append(
                f"- {name} is scheduled to start {row.start_time:%Y-%m-%d %H:%M} UTC"
            )
        if row.end_time is not None and row.end_time < now:
            lines.append(f"- {name} ended {row.end_time:%Y-%m-%d %H:%M} UTC")
        held = HELD.get((row.effective_status or "").upper())
        if held and row.delivery == Delivery.ACTIVE:
            lines.append(f"- {name} {held}")
        if row.daily_budget_minor and minimum and row.daily_budget_minor < minimum:
            lines.append(
                f"- {name}: daily budget {money(row.daily_budget_minor, campaign.currency)} "
                f"is under the ad account's minimum {money(minimum, campaign.currency)}"
            )
    return lines


def _adverts(
    db: Session, *, owner: User, campaign: Campaign, now: datetime
) -> list[str]:
    adverts = list(
        db.scalars(
            select(Ad)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .where(Ad.owner_id == owner.id, AdSet.campaign_id == campaign.id)
        )
    )
    if not adverts:
        return ["- it has no adverts mirrored"]
    running = [row for row in adverts if row.delivery == Delivery.ACTIVE]
    pending = [row for row in adverts if row.delivery == Delivery.PENDING]
    refused = [row for row in adverts if row.delivery == Delivery.REJECTED]
    lines: list[str] = []
    if pending:
        oldest = min(row.created_at for row in pending)
        late = now - oldest > LONG_REVIEW
        lines.append(
            f"- {len(pending)} of {len(adverts)} adverts wait for Meta's review"
            + (
                " for more than a day - longer than Meta's usual; a request to "
                "Support is right"
                if late
                else " - Meta usually reviews within a day"
            )
        )
    if refused:
        lines.append(
            f"- {len(refused)} of {len(adverts)} adverts were refused - "
            "`ad_details` has each one's ready fix"
        )
    if not running:
        lines.append("- no advert in it is running")
    return lines


def _account(campaign: Campaign) -> list[str]:
    account = campaign.ad_account
    lines: list[str] = []
    if account.may_advertise is False or account.payment_due:
        lines.append(
            "- its ad account cannot advertise right now - `account_health` "
            "says why and where to settle it"
        )
    if 0 < account.spend_cap_minor <= account.amount_spent_minor:
        lines.append("- its ad account's spending limit is used up")
    held = HELD.get((campaign.effective_status or "").upper())
    if held:
        lines.append(f"- the campaign {held}")
    return lines


__all__ = ["stalled_lines"]
