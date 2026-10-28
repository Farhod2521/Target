"""Relationships from a table to itself read the parent, not a child."""

from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import GeoArea
from app.modules.ads.selectors.audiences_chosen import picked_areas
from app.modules.supportchat.models import SupportConversation, SupportMessage


def _areas(db: Session) -> tuple[GeoArea, GeoArea]:
    region = GeoArea(
        key="uz-tash-r", country_code="UZ", kind="region", name_uz="Viloyat"
    )
    db.add(region)
    db.flush()
    city = GeoArea(
        key="uz-tash-c",
        country_code="UZ",
        kind="city",
        name_uz="Shahar",
        parent_id=region.id,
    )
    other = GeoArea(key="uz-sam-c", country_code="UZ", kind="city", name_uz="Boshqa")
    db.add_all([city, other])
    db.commit()
    return region, city


def test_a_city_reads_its_region(db: Session) -> None:
    region, city = _areas(db)

    assert city.parent is not None and city.parent.id == region.id
    assert region.parent is None


def test_a_city_inside_a_ticked_region_is_not_sent_twice(db: Session) -> None:
    _areas(db)

    picked = picked_areas(
        db,
        keys=["uz-tash-r", "uz-tash-c", "uz-sam-c"],
        previous=[],
        country_code="uz",
        limit=10,
    )

    assert [row["area"] for row in picked] == ["uz-tash-r", "uz-sam-c"]


def test_a_reply_reads_the_message_it_quotes(db: Session) -> None:
    owner = User(
        email="q@example.com", full_name="Q", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.flush()
    chat = SupportConversation(owner_id=owner.id)
    db.add(chat)
    db.flush()
    first = SupportMessage(owner_id=owner.id, conversation_id=chat.id, body="Savol")
    db.add(first)
    db.flush()
    reply = SupportMessage(
        owner_id=owner.id, conversation_id=chat.id, body="Javob", reply_to_id=first.id
    )
    db.add(reply)
    db.commit()

    assert reply.reply_to is not None and reply.reply_to.id == first.id
    assert first.reply_to is None
