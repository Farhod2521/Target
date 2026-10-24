import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.hooks import fire, on
from app.modules.accounts.models import User
from app.modules.accounts.services import USER_REGISTERED
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.referrals.models import ReferralBinding
from app.modules.referrals.selectors import code_owner, may_invite

logger = logging.getLogger(__name__)
REFERRAL_BOUND = "referrals.bound"


def bind_referrer(db: Session, *, invited: User, code: str) -> ReferralBinding | None:
    normalised = code.strip().upper()
    if not normalised:
        return None
    referrer = _inviter(db, code=normalised, invited=invited)
    if referrer is None:
        return None
    existing = _binding(db, invited)
    if existing is not None:
        return existing
    now = utcnow()
    binding = ReferralBinding(
        owner_id=invited.id,
        referrer_id=referrer.id,
        code=normalised,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(binding)
    except IntegrityError:
        return _binding(db, invited)
    emit(
        db,
        owner_id=invited.id,
        name=EventName.REFERRAL_BOUND,
        aggregate_type="referral_binding",
        aggregate_id=binding.id,
        payload={"referrer_id": str(referrer.id), "code": normalised},
        occurred_at=now,
    )
    fire(REFERRAL_BOUND, db=db, referrer=referrer, invited=invited)
    return binding


@on(USER_REGISTERED)
def _on_registered(
    *, db: Session, user: User, referral_code: str = "", **_: object
) -> None:
    bind_referrer(db, invited=user, code=referral_code)


def _binding(db: Session, invited: User) -> ReferralBinding | None:
    return db.scalar(
        select(ReferralBinding).where(ReferralBinding.owner_id == invited.id)
    )


def _inviter(db: Session, *, code: str, invited: User) -> User | None:
    referrer = code_owner(db, code=code)
    if referrer is None or referrer.id == invited.id:
        return None
    if not may_invite(db, owner_id=referrer.id):
        logger.info(
            "referral code owner closed by the office",
            extra={"owner_id": str(referrer.id)},
        )
        return None
    return referrer
