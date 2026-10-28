from collections.abc import Callable

from sqlalchemy.orm import Session


def atomic[T](db: Session, run: Callable[[], T]) -> T:
    """Run a write and commit it; anything raised rolls it all back."""
    try:
        result = run()
    except BaseException:
        db.rollback()
        raise
    db.commit()
    return result
