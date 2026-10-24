import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import Db
from app.common import tokens
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


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, db: Db) -> User:
    return services.register_user(
        db,
        email=body.email,
        full_name=body.full_name,
        password=body.password,
        phone=clean_phone(body.phone),
        language=body.language,
        referral_code=body.referral_code,
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
