import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from sqlalchemy import JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.common.config import settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


Json = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


# JIT off: the planner's cost for the office's wide per-account reads (the
# sales pool) crosses jit_above_cost, and compiling them took ~9s of a 250ms
# query on every request. No screen here reads enough rows to win it back.
engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_max_size,
    connect_args=(
        {"options": "-c jit=off"}
        if settings.sqlalchemy_url.startswith("postgresql")
        else {}
    ),
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_ON_COMMIT = "on_commit"


def on_commit(db: Session, callback: Callable[[], object]) -> None:
    """Run ``callback`` once the session's transaction commits, like Django's."""
    db.info.setdefault(_ON_COMMIT, []).append(callback)


@event.listens_for(Session, "after_commit")
def _run_on_commit(db: Session) -> None:
    # Fired for a savepoint too, when the row is still nobody else's to read.
    if db.in_nested_transaction():
        return
    callbacks = db.info.pop(_ON_COMMIT, [])
    for callback in callbacks:
        callback()


@event.listens_for(Session, "after_rollback")
def _drop_on_commit(db: Session) -> None:
    if not db.in_nested_transaction():
        db.info.pop(_ON_COMMIT, None)
