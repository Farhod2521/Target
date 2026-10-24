"""The pictures an ad account holds itself, and the one a proposal would put on an advert."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import MediaKind
from app.modules.ads.models import MediaAsset
from app.modules.agent.constants import SuggestionKind
from app.modules.agent.models import AgentSuggestion
from app.modules.integrations.models import AdAccount
from core.agent import LibraryImage

LIBRARY_IMAGES = 50


def own_pictures(
    db: Session, *, owner: User, account: AdAccount
) -> tuple[LibraryImage, ...]:
    """The account's own pictures, newest first, video covers left out."""
    from app.modules.ads.selectors import video_cover_hashes

    rows = db.execute(
        select(MediaAsset.id, MediaAsset.external_id, MediaAsset.name)
        .where(
            MediaAsset.owner_id == owner.id,
            MediaAsset.provider == account.provider,
            MediaAsset.kind == MediaKind.IMAGE,
            MediaAsset.ad_account_id == account.id,
            MediaAsset.external_id.not_in(video_cover_hashes(owner, account)),
        )
        .order_by(
            MediaAsset.created_at_provider.desc().nulls_last(),
            MediaAsset.created_at.desc(),
        )
        .limit(LIBRARY_IMAGES)
    )
    return tuple(
        LibraryImage(asset_id=str(pk), image_hash=str(image_hash), name=str(name or ""))
        for pk, image_hash, name in rows
    )


@dataclass(frozen=True, slots=True)
class CardPicture:
    """What the card draws: the library's own preview and the file's name."""

    url: str
    name: str


def card_pictures(
    db: Session, *, owner: User, rows: list[AgentSuggestion]
) -> dict[str, CardPicture]:
    """``{library row id: picture}`` for every new-picture proposal here."""
    import uuid

    wanted: set[uuid.UUID] = set()
    for row in rows:
        raw = (row.payload or {}).get("asset_id")
        if row.kind == SuggestionKind.NEW_PICTURE and raw:
            try:
                wanted.add(uuid.UUID(str(raw)))
            except ValueError:
                continue
    if not wanted:
        return {}
    return {
        str(pk): CardPicture(url=str(url or ""), name=str(name or ""))
        for pk, url, name in db.execute(
            select(MediaAsset.id, MediaAsset.thumbnail_url, MediaAsset.name).where(
                MediaAsset.owner_id == owner.id, MediaAsset.id.in_(wanted)
            )
        )
    }


__all__ = ["LIBRARY_IMAGES", "CardPicture", "card_pictures", "own_pictures"]
