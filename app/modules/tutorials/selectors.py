"""Reading tutorials: the list with its filters, and what a lesson's video is."""

import re
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.tutorials.constants import PAGE_SIZE
from app.modules.tutorials.models import Tutorial

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com")


@dataclass(frozen=True, slots=True)
class TutorialPage:
    rows: list[Tutorial]
    total: int
    offset: int
    has_more: bool

    @property
    def next_offset(self) -> int | None:
        return self.offset + len(self.rows) if self.has_more else None


def _escaped(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def tutorial_page(
    db: Session,
    *,
    type: str = "",
    place: str = "",
    term: str = "",
    active: bool | None = None,
    offset: int = 0,
) -> TutorialPage:
    """Newest first. Empty filters narrow nothing; the term is part of the
    title or the description; a place keeps the lessons that screen shows."""
    query = select(Tutorial)
    if type:
        query = query.where(Tutorial.type == type)
    if place:
        query = query.where(Tutorial.places.contains([place]))
    if active is not None:
        query = query.where(Tutorial.is_active.is_(active))
    if term:
        like = f"%{_escaped(term)}%"
        query = query.where(
            or_(
                Tutorial.title.ilike(like, escape="\\"),
                Tutorial.description.ilike(like, escape="\\"),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(
            query.order_by(Tutorial.created_at.desc(), Tutorial.id)
            .offset(offset)
            .limit(PAGE_SIZE + 1)
        )
    )
    return TutorialPage(
        rows=rows[:PAGE_SIZE],
        total=total,
        offset=offset,
        has_more=len(rows) > PAGE_SIZE,
    )


def tutorial_by_id(
    db: Session, tutorial_id: uuid.UUID, *, active_only: bool
) -> Tutorial | None:
    row = db.get(Tutorial, tutorial_id)
    if row is None or (active_only and not row.is_active):
        return None
    return row


def youtube_id(url: str) -> str:
    """The video's id in a YouTube link, or "" for any other link."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    found = ""
    if host in ("youtu.be", "www.youtu.be"):
        found = parsed.path.strip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS or host == "www.youtube-nocookie.com":
        if parsed.path == "/watch":
            found = (parse_qs(parsed.query).get("v") or [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v"):
                found = parts[1]
    return found if _YOUTUBE_ID.match(found) else ""
