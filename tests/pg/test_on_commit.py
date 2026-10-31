"""What waits for the commit waits for the real one, not for a savepoint."""

from sqlalchemy.orm import Session

from app.common.db import on_commit


def test_a_savepoint_is_not_the_commit(db: Session) -> None:
    ran: list[str] = []
    on_commit(db, lambda: ran.append("sent"))
    with db.begin_nested():
        pass
    assert ran == []
    db.commit()
    assert ran == ["sent"]


def test_a_rollback_drops_what_waited(db: Session) -> None:
    ran: list[str] = []
    with db.begin_nested():
        pass
    on_commit(db, lambda: ran.append("sent"))
    db.rollback()
    db.commit()
    assert ran == []
