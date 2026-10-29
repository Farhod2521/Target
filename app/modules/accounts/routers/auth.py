import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import Db, client_address
from app.common import throttle, tokens
from app.common.db import utcnow
from app.modules.accounts import services
from app.modules.accounts.models import User
from app.modules.accounts.phone import clean_phone
from app.modules.accounts.schemas import (
    LoginIn,
    RefreshIn,
    SignupIn,
    TokenPair,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _pair(user: User) -> TokenPair:
    now = utcnow()
    return TokenPair(
        access_token=tokens.issue(subject=str(user.id), kind="access", now=now),
        refresh_token=tokens.issue(subject=str(user.id), kind="refresh", now=now),
    )


SIGNUP_BUCKET = "signup:address"
SIGNUPS_PER_HOUR = 20


class SignedUp(TokenPair):
    user: UserOut


@router.post("/signup", response_model=SignedUp, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, request: Request, db: Db) -> SignedUp:
    """The form opens the account and signs it in; the email is confirmed later."""
    if not throttle.hit(
        bucket=SIGNUP_BUCKET,
        key=client_address(request),
        limit=SIGNUPS_PER_HOUR,
        window_seconds=3600,
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring.",
        )
    user = services.sign_up(
        db,
        email=body.email,
        full_name=body.full_name,
        password=body.password,
        phone=clean_phone(body.phone),
        language=body.language,
        referral_code=body.referral_code,
    )
    pair = _pair(user)
    return SignedUp(
        user=UserOut.model_validate(user),
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


@router.post("/login", response_model=TokenPair)
def login(body: LoginIn, db: Db) -> TokenPair:
    return _pair(services.authenticate(db, email=body.email, password=body.password))


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshIn, db: Db) -> TokenPair:
    subject = tokens.read(body.refresh_token, kind="refresh")
    try:
        user = db.get(User, uuid.UUID(subject or ""))
    except ValueError:
        user = None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Qayta kiring.")
    return _pair(user)
