"""Why Meta will not run an advert, in the shape every refusal is drawn in.

The reason lives on the advert: a campaign's own ``issue_summary`` says nothing
when one of its adverts was turned down. So each level finds its first such
advert here, and one policy is one key however many adverts break it.
"""

import hashlib
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.contract import Refusal, RefusalFix
from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.creatives import with_content
from app.modules.ads.selectors.failures import feedback_text
from core.agent.refusal_cause import RefusalCause, refusal_cause

# An advert that shows an existing page post: its words are changed on the network.
POST_KINDS: Final = frozenset({"post", "page_post", "existing_post", "boost"})
TITLE: Final = "Meta reklamani rad etdi"
RESEND: Final = "Reklamani saqlang: Meta uni qayta ko'rib chiqadi."
SWAP_LABEL: Final = "Matn va rasmni almashtirish"
GUIDES: Final[dict[RefusalCause, tuple[str, tuple[str, ...]]]] = {
    "words": (
        "Sabab — reklama matni.",
        ("Pastda Meta yozgan qoidani o'qing.", "Matnni shu qoidaga moslang.", RESEND),
    ),
    "picture": (
        "Sabab — rasm yoki video.",
        ("Boshqasini qo'ying: matnni o'zgartirish yordam bermaydi.", RESEND),
    ),
    "site": (
        "Sabab — reklama olib boradigan sayt.",
        (
            "Sayt ochilishini tekshiring.",
            "Reklamadagi va'da saytda ham borligini tekshiring.",
            RESEND,
        ),
    ),
    "offer": (
        "Sabab — mahsulot yoki xizmatning o'zi Meta qoidalarida cheklangan.",
        (
            "Matn yoki rasmni o'zgartirish yordam bermaydi.",
            "Xato deb hisoblasangiz, Ads Manager'da qayta ko'rib chiqishni so'rang.",
        ),
    ),
    "account": (
        "Sabab — reklama akkaunti yoki sahifa.",
        ("Meta'ning «Account Quality» sahifasida holatini tekshiring.",),
    ),
    "unknown": (
        "Meta bu reklamani ishga tushirmadi.",
        ("Pastda Meta yozgan sababni o'qing.", "Shu qismni tuzating.", RESEND),
    ),
}
# Causes a new advert cannot cure keep their own steps.
STANDING: Final = frozenset({"offer", "account"})
# A post cannot be swapped in place: the way out is another advert.
POST_STEPS: Final = (
    "Bu reklama tayyor post'dan qurilgan: post'ni shu yerda almashtirib bo'lmaydi.",
    "Guruhga boshqa rasm, video yoki post bilan yangi reklama qo'shing.",
    "Eski reklamani o'chiring.",
)


def turned_down(ad: Any) -> bool:
    return ad.delivery == Delivery.REJECTED


def complaint_of(ad: Any) -> str:
    """Meta's words about this advert, or its group's when the fault is there."""
    feedback = feedback_text(ad.review_feedback)
    issues = [
        " — ".join(
            part
            for part in (str(row.get("summary", "")), str(row.get("message", "")))
            if part
        )
        for row in (ad.issues if isinstance(ad.issues, list) else ())
        if isinstance(row, dict)
    ]
    said = [line for line in (feedback, *issues) if line]
    return "\n".join(said) or ad.issue_summary or ad.adset.issue_summary


def review_key(ad: Any) -> str:
    """One name for one complaint: the policy, else what the issue says.

    The name is hashed because Meta words it in the token's language and at
    any length, and a key is short.
    """
    said = complaint_of(ad)
    if not said:
        return ""
    codes = [code for code in (ad.issue_codes or ()) if code]
    feedback = feedback_text(ad.review_feedback)
    name = (
        feedback.partition(":")[0]
        if feedback
        else f"issue {codes[0]}"
        if codes
        else said
    )
    digest = hashlib.sha256(name.strip().casefold().encode()).hexdigest()[:16]
    return f"review:{ad.provider}:{digest}"


def rejection_of(ad: Any) -> dict[str, Any] | None:
    """The refusal to open from this advert, or nothing when it runs.

    The written answer is read by key, as for every refusal kept on a row.
    """
    if ad is None or not turned_down(ad):
        return None
    said = complaint_of(ad)
    cause = refusal_cause(said)
    sentence, steps = GUIDES[cause]
    post = (getattr(getattr(ad, "content", None), "kind", "") or "") in POST_KINDS
    key = review_key(ad)
    return Refusal(
        key=key or None,
        title=TITLE,
        cause=sentence,
        steps=list(POST_STEPS if post and cause not in STANDING else steps),
        provider_words=said or None,
        explaining=bool(key),
        fix=None
        if post
        else RefusalFix(
            label=SWAP_LABEL,
            url=reverse("ads:ad_edit", kwargs={"external_id": ad.external_id}),
        ),
    ).model_dump(by_alias=True)


def first_turned_down(ads: Any) -> Any:
    return next((ad for ad in ads if turned_down(ad)), None)


def with_rejections(
    db: Session, *, owner: User, campaigns: list[Campaign]
) -> list[Campaign]:
    """Hang each campaign's first refused advert on it, for a list of rows."""
    found = db.execute(
        select(AdSet.campaign_id, Ad)
        .join(Ad, Ad.adset_id == AdSet.id)
        .where(
            Ad.owner_id == owner.id,
            Ad.delivery == Delivery.REJECTED,
            AdSet.campaign_id.in_([row.id for row in campaigns]),
        )
        .order_by(Ad.created_at)
    ).all()
    with_content(db, owner=owner, ads=[ad for _, ad in found])
    first: dict[Any, Ad] = {}
    for campaign_id, ad in found:
        first.setdefault(campaign_id, ad)
    for campaign in campaigns:
        campaign.rejected_ad = first.get(campaign.id)  # type: ignore[attr-defined]
    return campaigns


__all__ = [
    "POST_KINDS",
    "complaint_of",
    "first_turned_down",
    "rejection_of",
    "review_key",
    "turned_down",
    "with_rejections",
]
