"""Whether the stored figures agree with Ads Manager's own account total.

Each night the product reads Meta's account total for the last closed days
again and keeps it beside the sum it stored (``metrics.services.check``).
A client who says «Ads Manager shows another number» was answered with a
guess; this says, per ad account, which days were checked and which were
apart, with both figures - Ads Manager's being the one that counts.
"""

from collections.abc import Iterable
from datetime import date
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.chat.selectors.lookups.common import money

APART_ROWS: Final = 5


def meta_check_lines(
    db: Session,
    *,
    owner: User,
    campaign_ids: Iterable[str],
    since: date,
    until: date,
) -> list[str]:
    from app.modules.ads.models import Campaign
    from app.modules.integrations.models import AdAccount
    from app.modules.metrics.models import MetricsCheck

    wanted = list(campaign_ids)
    if not wanted:
        return []
    accounts = list(
        db.scalars(
            select(AdAccount)
            .join(Campaign, Campaign.ad_account_id == AdAccount.id)
            .where(Campaign.owner_id == owner.id, Campaign.external_id.in_(wanted))
            .distinct()
        )
    )
    if not accounts:
        return []
    checks = list(
        db.scalars(
            select(MetricsCheck)
            .where(
                MetricsCheck.owner_id == owner.id,
                MetricsCheck.ad_account_id.in_([row.id for row in accounts]),
                MetricsCheck.day >= since,
                MetricsCheck.day <= until,
            )
            .order_by(MetricsCheck.day)
        )
    )
    lines = ["", "## Checked against Ads Manager's own account total (each night)"]
    for account in accounts:
        mine = [row for row in checks if row.ad_account_id == account.id]
        name = f"«{account.name or account.external_id}»"
        if not mine:
            lines.append(f"- {name}: no day of this window was checked yet")
            continue
        apart = [row for row in mine if row.differs]
        if not apart:
            lines.append(
                f"- {name}: {len(mine)} day(s) checked, each the same as Ads Manager"
            )
            continue
        lines.append(
            f"- {name}: {len(mine)} day(s) checked, {len(apart)} apart from Ads "
            "Manager. Ads Manager's figure is the right one; a day apart means "
            "a campaign or page this product does not read, or Meta corrected "
            "the day after it was read:"
        )
        for row in apart[-APART_ROWS:]:
            ours, theirs = row.ours or {}, row.theirs or {}
            currency = account.currency
            lines.append(
                f"  - {row.day}: here spend {money(int(ours.get('spend_minor', 0)), currency)}, "
                f"impressions {int(ours.get('impressions', 0))}; Ads Manager spend "
                f"{money(int(theirs.get('spend_minor', 0)), currency)}, impressions "
                f"{int(theirs.get('impressions', 0))}"
            )
    return lines


__all__ = ["meta_check_lines"]
