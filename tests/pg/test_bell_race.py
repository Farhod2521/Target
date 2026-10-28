"""Two tabs pressing the bell at once both succeed."""

import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.notifications.models import InboxSeen
from app.modules.notifications.services.notices import mark_seen


def test_two_tabs_press_the_bell_together(pg_factory: sessionmaker[Session]) -> None:
    with pg_factory() as db:
        owner = User(
            email="bell@example.com", full_name="B", password="!", date_joined=utcnow()
        )
        db.add(owner)
        db.commit()
        owner_id = owner.id
    keys = frozenset({"suggestion:1", "stop:2"})
    failures: list[BaseException] = []

    first = pg_factory()
    mark_seen(first, owner=first.get(User, owner_id), keys=keys)

    def second_tab() -> None:
        with pg_factory() as db:
            try:
                mark_seen(db, owner=db.get(User, owner_id), keys=keys)
                db.commit()
            except BaseException as exc:
                failures.append(exc)

    other = threading.Thread(target=second_tab)
    other.start()
    other.join(timeout=1)
    first.commit()
    first.close()
    other.join(timeout=10)

    assert failures == []
    with pg_factory() as db:
        count = db.scalar(
            select(func.count())
            .select_from(InboxSeen)
            .where(InboxSeen.owner_id == owner_id)
        )
    assert count == 2
