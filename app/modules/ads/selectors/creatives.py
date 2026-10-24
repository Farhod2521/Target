from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdCreative

_STANDING: tuple[str, ...] = (
    Delivery.ACTIVE,
    Delivery.PENDING,
    Delivery.REJECTED,
    Delivery.PAUSED_ABOVE,
    Delivery.PAUSED,
    Delivery.FINISHED,
    Delivery.UNKNOWN,
)


@dataclass(frozen=True, slots=True)
class CreativeState:
    delivery: str
    label: Any
    ad_external_id: str
    name: str = ""


def creative_ids_by_ad(
    db: Session, *, owner: User, provider: str, ad_external_ids: list[str]
) -> dict[str, str]:
    if not ad_external_ids:
        return {}
    return dict(
        db.execute(
            select(Ad.external_id, Ad.creative_external_id).where(
                Ad.owner_id == owner.id,
                Ad.provider == provider,
                Ad.external_id.in_(ad_external_ids),
                Ad.creative_external_id != "",
            )
        ).all()
    )


def creatives_by_external_id(
    db: Session, *, owner: User, provider: str, external_ids: list[str]
) -> dict[str, AdCreative]:
    if not external_ids:
        return {}
    rows = db.scalars(
        select(AdCreative).where(
            AdCreative.owner_id == owner.id,
            AdCreative.provider == provider,
            AdCreative.external_id.in_(external_ids),
        )
    )
    return {row.external_id: row for row in rows}


def creative_of(db: Session, *, owner: User, ad: Ad) -> AdCreative | None:
    if not ad.creative_external_id:
        return None
    return db.scalars(
        select(AdCreative).where(
            AdCreative.owner_id == owner.id,
            AdCreative.provider == ad.provider,
            AdCreative.external_id == ad.creative_external_id,
        )
    ).first()


def with_content(db: Session, *, owner: User, ads: list[Ad]) -> list[Ad]:
    creatives = creatives_by_external_id(
        db,
        owner=owner,
        provider=ads[0].provider if ads else "",
        external_ids=[ad.creative_external_id for ad in ads if ad.creative_external_id],
    )
    for ad in ads:
        ad.content = creatives.get(ad.creative_external_id)  # type: ignore[attr-defined]
    return ads


def creative_states(
    db: Session, *, owner: User, campaign: Any
) -> dict[str, CreativeState]:
    from app.modules.ads.models import AdSet

    rows = db.execute(
        select(Ad.creative_external_id, Ad.external_id, Ad.delivery, Ad.name)
        .join(AdSet, AdSet.id == Ad.adset_id)
        .where(Ad.owner_id == owner.id, AdSet.campaign_id == campaign.id)
    )
    labels = dict(Delivery.choices)
    order = {value: rank for rank, value in enumerate(_STANDING)}
    last = len(order)
    found: dict[str, CreativeState] = {}
    for creative_id, ad_id, delivery, name in rows:
        key = creative_id or ad_id
        standing = found.get(key)
        if standing is not None and order.get(standing.delivery, last) <= order.get(
            delivery, last
        ):
            continue
        found[key] = CreativeState(
            delivery=delivery,
            label=labels.get(delivery, delivery),
            ad_external_id=ad_id,
            name=name,
        )
    return found


def video_cover_hashes(owner: User, account: Any):  # type: ignore[no-untyped-def]
    """The hashes of every cover a video creative on this account names, as a subquery."""
    from sqlalchemy import type_coerce
    from sqlalchemy.dialects.postgresql import JSONB

    cover = type_coerce(AdCreative.story_raw, JSONB)["video_data"]["image_hash"].astext
    return select(cover).where(
        AdCreative.owner_id == owner.id,
        AdCreative.ad_account_id == account.id,
        cover.is_not(None),
        cover != "",
    )
