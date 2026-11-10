"""Erasing people who are on a board, against PostgreSQL with Django's
foreign keys: a client takes their cards and history along; a staff member
leaves the cards they worked, with the link emptied."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.common.deletion import delete_rows
from app.modules.accounts.services.members import purge_owned_rows
from app.modules.boards.models import BoardCard, BoardCardEvent


def _person(db: Session, email: str, *, staff: bool = False) -> User:
    person = User(
        email=email, full_name=email, password="!", is_staff=staff, date_joined=utcnow()
    )
    db.add(person)
    db.flush()
    return person


def _card(db: Session, owner: User, manager: User) -> BoardCard:
    now = utcnow()
    card = BoardCard(
        board="sales",
        owner_id=owner.id,
        column_code="new_lead",
        manager_id=manager.id,
        opened_at=now,
        column_since=now,
    )
    db.add(card)
    db.flush()
    db.add(
        BoardCardEvent(
            card_id=card.id,
            owner_id=owner.id,
            kind="taken",
            to_column="new_lead",
            actor_id=manager.id,
        )
    )
    db.commit()
    return card


def _count(db: Session, model: type) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_a_purged_client_takes_their_card_and_its_history(db: Session) -> None:
    client = _person(db, "mijoz@example.com")
    manager = _person(db, "sotuv@example.com", staff=True)
    _card(db, client, manager)

    deleted = purge_owned_rows(db, user=client)
    delete_rows(db, User.__table__, User.id == client.id)
    db.commit()

    assert deleted["boards.BoardCard"] == 1
    assert _count(db, BoardCard) == 0 and _count(db, BoardCardEvent) == 0


def test_a_purged_staff_member_leaves_the_cards_they_worked(db: Session) -> None:
    client = _person(db, "mijoz@example.com")
    manager = _person(db, "sotuv@example.com", staff=True)
    card = _card(db, client, manager)

    purge_owned_rows(db, user=manager)
    delete_rows(db, User.__table__, User.id == manager.id)
    db.commit()
    db.expire_all()

    kept = db.get(BoardCard, card.id)
    assert kept is not None and kept.manager_id is None
    event = db.scalar(select(BoardCardEvent))
    assert event is not None and event.actor_id is None
