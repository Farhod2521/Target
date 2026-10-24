import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.referrals.constants import ReferralMode
from app.modules.referrals.models import ReferralAccess, ReferralCode


def referral_mode(db: Session, *, owner_id: uuid.UUID) -> ReferralMode:
    mode = db.scalar(
        select(ReferralAccess.mode).where(ReferralAccess.owner_id == owner_id)
    )
    return ReferralMode(mode) if mode else ReferralMode.AUTO


def may_invite(db: Session, *, owner_id: uuid.UUID) -> bool:
    return referral_mode(db, owner_id=owner_id) != ReferralMode.CLOSED


def code_owner(db: Session, *, code: str) -> User | None:
    normalised = code.strip().upper()
    if not normalised:
        return None
    owner_id = db.scalar(
        select(ReferralCode.owner_id).where(ReferralCode.code == normalised)
    )
    return db.get(User, owner_id) if owner_id else None
