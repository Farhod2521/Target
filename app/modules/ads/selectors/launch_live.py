"""What one launch put on the provider, as the mirror last saw it.

Beside :mod:`app.modules.ads.selectors.launch_settings`, which reads what was
prepared: this reads what the sync brought back, because a library picture's
address stops working and an advert added in Ads Manager is still this
launch's money. Nothing asks the provider anything.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from metaads.writing import is_dry_run_id
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    BUTTON_LABELS,
    DELIVERY_LABELS,
    LAUNCH_STATUS_LABELS,
    LAUNCH_STEP_LABELS,
    MEDIA_KIND_LABELS,
    LaunchStep,
    MediaKind,
)
from app.modules.ads.models import Ad, AdCreative, AdSet, CampaignLaunch, MediaAsset
from app.modules.ads.selectors.launch_settings import (
    POST_KINDS,
    post_address,
    video_address,
)
from app.modules.leads.constants import LeadFormStatus
from app.modules.leads.selectors import FormOption, form_card, forms_by_external_id

FACEBOOK_POST: Final = "https://www.facebook.com/{post}"
FACEBOOK_POST_LABEL: Final = "Facebook posti"


@dataclass(frozen=True, slots=True)
class LivePost:
    """The post behind an advert, with the address it opens at."""

    external_id: str
    url: str
    kind_label: str
    text: str
    picture: str


@dataclass(frozen=True, slots=True)
class LiveAd:
    """One advert on the provider, as the last sync left it."""

    external_id: str
    name: str
    delivery: str
    delivery_label: str
    problem: str
    picture: str
    is_video: bool
    text: str
    headline: str
    description: str
    link: str
    button: str
    post: LivePost | None
    video_url: str


@dataclass(frozen=True, slots=True)
class LiveForm:
    """A lead form; ``card`` is ``None`` until the form sync has read it."""

    external_id: str
    card: FormOption | None
    collecting: bool = True
    privacy_url: str = ""
    locale: str = ""


@dataclass(frozen=True, slots=True)
class LaunchLive:
    status: str
    step: str
    error: str
    delivery_note: str
    qualified: bool
    ads: tuple[LiveAd, ...]
    forms: tuple[LiveForm, ...]


@dataclass(frozen=True, slots=True)
class _Library:
    videos: dict[str, str]
    images: dict[str, str]
    posts: dict[str, MediaAsset]


def launch_live(db: Session, *, launch: CampaignLaunch) -> LaunchLive:
    ads = launch_ads(db, launch=launch)
    creatives = _creatives(db, launch, ads)
    library = _library(db, launch, creatives.values())
    return LaunchLive(
        status=str(LAUNCH_STATUS_LABELS.get(launch.status, launch.status)),
        step=str(LAUNCH_STEP_LABELS.get(launch.step, "")) if launch.step else "",
        error=launch.error_message,
        delivery_note=launch.delivery_note,
        qualified=launch.buy_qualified_leads,
        ads=tuple(
            _live(ad, creatives.get(ad.creative_external_id), library) for ad in ads
        ),
        forms=_forms(db, launch, ads),
    )


def ad_problem(ad: Ad) -> str:
    """The refusal first, then the delivery fault, as one line each."""
    feedback = ad.review_feedback if isinstance(ad.review_feedback, dict) else {}
    overall = feedback.get("overall")
    lines = [
        f"{policy}: {str(reason).strip()}"
        for policy, reason in (overall.items() if isinstance(overall, dict) else ())
        if str(reason).strip()
    ]
    if ad.issue_summary:
        lines.append(ad.issue_summary)
    return "\n".join(lines)


def _real(ids: list[str]) -> list[str]:
    return [item for item in ids if item and not is_dry_run_id(item)]


def launch_ads(db: Session, *, launch: CampaignLaunch) -> list[Ad]:
    """The adverts the launch made, and any added later to its ad groups."""
    refs = launch.created_refs if isinstance(launch.created_refs, dict) else {}
    ad_ids = _real(ref_field.ref_ids(refs, LaunchStep.AD))
    adset_ids = _real(ref_field.ref_ids(refs, LaunchStep.ADSET))
    if not ad_ids and not adset_ids:
        return []
    return list(
        db.scalars(
            select(Ad)
            .options(joinedload(Ad.adset))
            .join(AdSet, AdSet.id == Ad.adset_id)
            .where(
                Ad.owner_id == launch.owner_id,
                Ad.provider == launch.provider,
                or_(Ad.external_id.in_(ad_ids), AdSet.external_id.in_(adset_ids)),
            )
            .order_by(Ad.created_at)
        )
    )


def _creatives(
    db: Session, launch: CampaignLaunch, ads: list[Ad]
) -> dict[str, AdCreative]:
    ids = [ad.creative_external_id for ad in ads if ad.creative_external_id]
    if not ids:
        return {}
    rows = db.scalars(
        select(AdCreative).where(
            AdCreative.owner_id == launch.owner_id,
            AdCreative.provider == launch.provider,
            AdCreative.external_id.in_(ids),
        )
    )
    return {row.external_id: row for row in rows}


def _library(
    db: Session, launch: CampaignLaunch, creatives: Iterable[AdCreative]
) -> _Library:
    """Where each creative's video plays, its picture is whole, its post opens."""
    ids = {
        key
        for row in creatives
        for key in (row.video_id, row.post_external_id, row.image_hash)
        if key
    }
    found = _Library(videos={}, images={}, posts={})
    if not ids:
        return found
    rows = db.scalars(
        select(MediaAsset).where(
            MediaAsset.owner_id == launch.owner_id,
            MediaAsset.provider == launch.provider,
            MediaAsset.kind.in_((MediaKind.VIDEO, MediaKind.IMAGE, *POST_KINDS)),
            MediaAsset.external_id.in_(ids),
        )
    )
    for asset in rows:
        if asset.kind in POST_KINDS:
            found.posts[asset.external_id] = asset
        if url := video_address(asset):
            found.videos[asset.external_id] = url
        elif asset.kind == MediaKind.IMAGE and asset.thumbnail_url.startswith(
            ("https://", "http://")
        ):
            found.images[asset.external_id] = asset.thumbnail_url
    return found


def _live(ad: Ad, creative: AdCreative | None, library: _Library) -> LiveAd:
    picture = ""
    if creative is not None:
        whole = library.images.get(creative.image_hash) if creative.image_hash else ""
        picture = whole or creative.thumbnail_url
    if not picture.startswith(("https://", "http://")):
        picture = ""
    button = creative.call_to_action if creative is not None else ""
    return LiveAd(
        external_id=ad.external_id,
        name=ad.name,
        delivery=ad.delivery,
        delivery_label=str(DELIVERY_LABELS.get(ad.delivery, ad.delivery)),
        problem=ad_problem(ad),
        picture=picture,
        is_video=bool(creative is not None and creative.video_id),
        text=creative.message if creative is not None else "",
        headline=creative.headline if creative is not None else "",
        description=creative.description if creative is not None else "",
        link=creative.link_url if creative is not None else "",
        button=str(BUTTON_LABELS.get(button, button)) if button else "",
        post=_post(creative, library, picture=picture),
        video_url=_video_of(creative, library.videos),
    )


def _post(
    creative: AdCreative | None, library: _Library, *, picture: str
) -> LivePost | None:
    """The library's own address where it has one; else a Facebook post id,
    ``<page>_<post>``, which opens at the provider's address."""
    if creative is None or not creative.post_external_id:
        return None
    post = creative.post_external_id
    asset = library.posts.get(post)
    url = post_address(asset) or (
        FACEBOOK_POST.format(post=post) if "_" in post else ""
    )
    return LivePost(
        external_id=post,
        url=url,
        kind_label=str(MEDIA_KIND_LABELS.get(asset.kind, asset.kind))
        if asset is not None
        else FACEBOOK_POST_LABEL,
        text=(asset.name if asset is not None else "") or creative.message,
        picture=(asset.thumbnail_url if asset is not None else "") or picture,
    )


def _video_of(creative: AdCreative | None, videos: dict[str, str]) -> str:
    if creative is None:
        return ""
    return videos.get(creative.video_id) or videos.get(creative.post_external_id, "")


def _forms(db: Session, launch: CampaignLaunch, ads: list[Ad]) -> tuple[LiveForm, ...]:
    """Every form this launch's adverts collect through, the chosen one first."""
    refs = launch.created_refs if isinstance(launch.created_refs, dict) else {}
    ids = list(
        dict.fromkeys(
            _real(
                [
                    launch.lead_form_external_id,
                    *ref_field.ref_ids(refs, LaunchStep.FORM),
                    *(ad.lead_form_external_id for ad in ads),
                ]
            )
        )
    )
    rows = forms_by_external_id(
        db, owner=launch.owner, provider=launch.provider, external_ids=ids
    )
    forms = []
    for external_id in ids:
        row = rows.get(external_id)
        if row is None:
            forms.append(LiveForm(external_id=external_id, card=None))
            continue
        forms.append(
            LiveForm(
                external_id=external_id,
                card=form_card(row),
                collecting=row.status == LeadFormStatus.ACTIVE,
                privacy_url=row.privacy_policy_url,
                locale=row.locale,
            )
        )
    return tuple(forms)


__all__ = [
    "LaunchLive",
    "LiveAd",
    "LiveForm",
    "LivePost",
    "ad_problem",
    "launch_ads",
    "launch_live",
]
