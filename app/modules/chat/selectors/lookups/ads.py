"""One advert: what it says, where it sends people, and how it is doing."""

from datetime import datetime
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.briefs import delivery_label
from app.modules.chat.selectors.lookups.common import (
    figure_sums,
    in_subscription,
    money,
    named,
    origin,
    refused,
    trimmed,
    window,
)
from app.modules.chat.selectors.scope import lead_window
from app.modules.leads.models import Lead, LeadForm
from app.modules.metrics.constants import MetricLevel, Ranking
from app.modules.metrics.models import MetricsDaily
from core.chat.lookups import AdLookup

WORDS_CHARS: Final = 1_500
RATINGS: Final = (
    ("quality", "quality_ranking"),
    ("engagement", "engagement_rate_ranking"),
    ("conversion", "conversion_rate_ranking"),
)


def ad_details(
    db: Session, *, owner: User, arguments: AdLookup, scope: PageScope, now: datetime
) -> str:
    """The advert, its words, its figures over the window."""
    ad = db.scalar(
        select(Ad)
        .join(AdSet, AdSet.id == Ad.adset_id)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(
            Ad.owner_id == owner.id,
            in_subscription(Campaign.ad_account_id),
            Ad.external_id == arguments.ad_id,
        )
        .limit(1)
    )
    if ad is None:
        return (
            f"No advert with id {arguments.ad_id} in the subscription. "
            "Use find to look it up by name."
        )
    if not scope.allows_adset(ad.adset.external_id):
        return refused(
            scope=scope,
            kind="advert",
            level="ad",
            external_id=ad.external_id,
            parent=ad.adset.external_id,
        )
    campaign = ad.adset.campaign
    lines = [
        "## Advert",
        f"- {named(ad.name, ad.external_id)} (id {ad.external_id}) - "
        f"{delivery_label(ad.delivery)}"
        + origin(
            scope, level="ad", external_id=ad.external_id, parent=ad.adset.external_id
        ),
        f"- ad group {named(ad.adset.name, ad.adset.external_id)} "
        f"(id {ad.adset.external_id}), campaign "
        f"{named(campaign.name, campaign.external_id)} (id {campaign.external_id})",
    ]
    lines += _words(db, owner=owner, ad=ad)
    lines += _figures(
        db, owner=owner, ad=ad, days=arguments.days, currency=campaign.currency
    )
    if ad.issue_summary:
        lines.append(f"- provider says: {ad.issue_summary}")
    lines += _refusals(ad)
    return "\n".join(lines)


def _words(db: Session, *, owner: User, ad: Ad) -> list[str]:
    creative = (
        db.scalar(
            select(AdCreative)
            .where(
                AdCreative.owner_id == owner.id,
                AdCreative.external_id == ad.creative_external_id,
            )
            .limit(1)
        )
        if ad.creative_external_id
        else None
    )
    lines: list[str] = []
    if creative is not None:
        lines += [
            f'- {label}: "{trimmed(value, WORDS_CHARS)}"'
            for label, value in (
                ("headline", creative.headline),
                ("words", creative.message),
                ("description", creative.description),
            )
            if value
        ]
        if creative.call_to_action:
            lines.append(f"- button: {creative.call_to_action}")
        if creative.link_url:
            lines.append(f"- links to: {creative.link_url}")
    if ad.lead_form_external_id:
        form = db.scalar(
            select(LeadForm.name)
            .where(
                LeadForm.owner_id == owner.id,
                LeadForm.external_id == ad.lead_form_external_id,
            )
            .limit(1)
        )
        lines.append(
            f"- lead form {named(form or '', ad.lead_form_external_id)} "
            f"(id {ad.lead_form_external_id})"
        )
    return lines or ["- its words have not been read yet"]


def _figures(
    db: Session, *, owner: User, ad: Ad, days: int, currency: str
) -> list[str]:
    from app.modules.leads.selectors import priced

    since, until = window(db, owner=owner, days=days)
    mine = (
        MetricsDaily.owner_id == owner.id,
        MetricsDaily.level == MetricLevel.AD,
        MetricsDaily.ad_external_id == ad.external_id,
    )
    sums = (
        db.execute(
            select(*figure_sums()).where(
                *mine, MetricsDaily.date >= since, MetricsDaily.date <= until
            )
        )
        .mappings()
        .one()
    )
    start, end = lead_window(db, owner=owner, since=since, until=until)
    leads = db.scalar(
        select(func.count(Lead.id)).where(
            Lead.owner_id == owner.id,
            Lead.is_test.is_(False),
            priced(),
            Lead.ad_external_id == ad.external_id,
            Lead.submitted_at >= start,
            Lead.submitted_at <= end,
        )
    )
    spend = int(sums["spend"] or 0)
    lines = [
        f"- {since} to {until}: spend {money(spend, currency)}, "
        f"shown {int(sums['shown'] or 0)}, "
        f"link clicks {int(sums['link_clicks'] or 0)}, "
        f"leads received {leads}, provider counted leads {int(sums['reported'] or 0)}"
    ]
    rated = db.scalar(
        select(MetricsDaily)
        .where(*mine, MetricsDaily.quality_ranking != "")
        .order_by(MetricsDaily.date.desc())
        .limit(1)
    )
    if rated is not None:
        steps = [
            f"{step} {Ranking(getattr(rated, column)).label}"
            for step, column in RATINGS
            if getattr(rated, column) in Ranking.values
            and getattr(rated, column) != Ranking.UNKNOWN
        ]
        if steps:
            lines.append(f"- provider rates it: {' / '.join(steps)}")
    return lines


def _refusals(ad: Ad) -> list[str]:
    """Why the provider turned the advert down, per policy it named."""
    feedback = ad.review_feedback if isinstance(ad.review_feedback, dict) else {}
    overall = feedback.get("overall")
    if not isinstance(overall, dict):
        return []
    return [
        f"- refused under {trimmed(policy, 80)}: {trimmed(reason, 300)}"
        for policy, reason in overall.items()
        if reason
    ]


__all__ = ["ad_details"]
