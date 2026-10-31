"""One advert's own pages: its words to swap, and how it looks.

The browser used to find which campaign an advert lives in by reading every
campaign's adverts; the mirror knows, and says so here.
"""

from typing import Any, Final
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.modules.accounts.models import User
from app.modules.ads.contract.tree import POST_KINDS, ad_item
from app.modules.ads.contract.words import network_of

# How often the preview was asked for while Meta's frame was still coming.
TRIES_KEY: Final = "ad-preview-tries:{user}:{ad}"
TRIES_SECONDS: Final = 10 * 60


def siblings(ad: Any) -> tuple[Any, list[Any]]:
    """The campaign an advert lives in, and every advert of it, in the list's order."""
    campaign = ad.adset.campaign
    return campaign, [row for group in campaign.adsets for row in group.ads]


def ad_edit_form(
    ad: Any,
    *,
    initial: dict[str, str],
    can_swap: bool,
    library: list[dict[str, Any]],
    forms: dict[str, Any] | None,
    limits: dict[str, int],
    early_hours: int,
) -> dict[str, Any]:
    campaign = ad.adset.campaign
    return {
        "external_id": ad.external_id,
        "campaign": {"id": str(campaign.id), "name": campaign.name},
        "network": network_of(ad.provider),
        "current": initial["headline"] or initial["message"] or ad.name,
        "can_swap": can_swap,
        "message": initial["message"],
        "headline": initial["headline"],
        "description": initial["description"],
        "limits": limits,
        "library": [
            {
                "id": row["id"],
                "name": row["name"],
                "kind": "video" if row["kind"] == "video" else "image",
                "thumb": row["thumbnail_url"] or None,
            }
            for row in library
            if row.get("is_eligible") is not False
        ],
        "forms": {
            "current_name": forms["current_name"],
            "options": [
                {
                    "id": row["external_id"],
                    "name": row["name"],
                    "questions": [_question(item) for item in row["questions"]],
                }
                for row in forms["options"]
            ],
        }
        if forms
        else None,
        "early_hours": early_hours,
    }


def _question(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("label") or item.get("key") or "")
    return str(item)


def preview_tries(owner: User, external_id: str, *, settled: bool) -> int:
    """This poll's number: counted here, as the screen asks without saying."""
    key = TRIES_KEY.format(user=owner.id, ad=external_id)
    if settled:
        cache.delete(key)
        return 0
    tries = int(cache.get(key) or 0)
    cache.set(key, tries + 1, TRIES_SECONDS)
    return tries


def ad_preview(
    db: Session,
    *,
    owner: User,
    ad: Any,
    content: Any,
    frame: Any,
    loading: bool,
) -> dict[str, Any]:
    from app.modules.ads.selectors import page_advertising
    from app.modules.integrations.models import PageAccount

    campaign, adverts = siblings(ad)
    position = next(
        (index for index, row in enumerate(adverts, start=1) if row.id == ad.id), 1
    )
    currency = ad.adset.currency or campaign.ad_account.currency
    base = ad_item(ad, position=position, chips=None, currency=currency)
    page_id = getattr(content, "page_id", "") or ""
    page = (
        db.scalar(
            select(PageAccount.name).where(
                PageAccount.owner_id == owner.id, PageAccount.external_id == page_id
            )
        )
        if page_id
        else None
    )
    if not page:
        shown = page_advertising(db, owner=owner).page
        page = shown.name if shown is not None else ""
    kind = getattr(content, "kind", "") or ""
    return {
        "campaign": {"id": str(campaign.id), "name": campaign.name},
        "siblings": [
            {"external_id": row.external_id, "position": index}
            for index, row in enumerate(adverts, start=1)
        ],
        "ad": base
        | {
            "headline": getattr(content, "headline", "") or base["headline"],
            "text": getattr(content, "message", "") or base["text"],
            "title": getattr(content, "headline", "") or "",
            "cta": getattr(content, "call_to_action", "") or "",
            "file": "",
            "site": _host(getattr(content, "link_url", "") or ""),
            "tagline": "",
            "offer": "",
            "description": getattr(content, "description", "") or "",
            "page": {"name": page, "initials": _initials(page)},
        },
        "content": "pending"
        if content is None
        else "post"
        if kind in POST_KINDS
        else "loaded",
        "frame": {"state": "ready", "src": frame.src, "height": frame.height}
        if frame is not None
        else {"state": "loading"}
        if loading
        else {"state": "gave_up"},
    }


def _host(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


def _initials(name: str) -> str:
    return "".join(word[0].upper() for word in name.split()[:2]) or "?"


__all__ = ["ad_edit_form", "ad_preview", "preview_tries", "siblings"]
