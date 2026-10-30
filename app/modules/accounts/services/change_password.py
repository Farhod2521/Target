from sqlalchemy.orm import Session

from app.common import throttle, tokens
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.common.passwords import (
    PasswordInvalid,
    check_password,
    make_password,
    validate_password,
)
from app.modules.accounts.constants import (
    PASSWORD_FAILURES_PER_USER,
    PASSWORD_WINDOW_SECONDS,
)
from app.modules.accounts.exceptions import TooManyAttempts, WrongPassword
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit

FAILURES_BUCKET = "password:user"


def change_password(
    db: Session, *, user: User, current_password: str, new_password: str
) -> User:
    """Check, replace, announce, and sign every other device out.

    A signed-in session is not permission to replace the password: the
    current one is asked for, and wrong answers are counted per account -
    asked before the hash is paid for, cleared once the right one comes.

    Every token issued before this moment stops working, as Django's session
    hash did: somebody changing a password they think is known is asking
    for exactly that. The caller hands the device that asked a fresh pair.
    """
    key = str(user.id)
    if throttle.spent(
        bucket=FAILURES_BUCKET, key=key, limit=PASSWORD_FAILURES_PER_USER
    ):
        raise TooManyAttempts
    if not check_password(current_password, user.password):
        throttle.record(
            bucket=FAILURES_BUCKET, key=key, window_seconds=PASSWORD_WINDOW_SECONDS
        )
        raise WrongPassword
    throttle.forget(bucket=FAILURES_BUCKET, key=key)
    try:
        validate_password(new_password, email=user.email, full_name=user.full_name)
    except PasswordInvalid as exc:
        raise InputRefused({"new_password": str(exc)}) from exc
    user.password = make_password(new_password)
    emit(
        db,
        owner_id=user.id,
        name=EventName.USER_PASSWORD_CHANGED,
        aggregate_type="user",
        aggregate_id=user.id,
    )
    db.commit()
    tokens.revoke_all(subject=key, now=utcnow())
    return user
