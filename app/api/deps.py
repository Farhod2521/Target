import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import get_db
from app.common.i18n import activate
from app.modules.accounts.models import User

_bearer = HTTPBearer(auto_error=False)


CRM_MEMBER_PATHS = ("/api/v1/crm", "/api/v1/auth", "/api/v1/account/language")


def signed_in(
    request: Request, credentials: HTTPAuthorizationCredentials | None, db: Session
) -> User:
    refused = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="Avval tizimga kiring.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    subject = (
        tokens.read(credentials.credentials, kind="access") if credentials else None
    )
    try:
        user = db.get(User, uuid.UUID(subject or ""))
    except ValueError:
        raise refused from None
    if user is None or not user.is_active:
        raise refused
    if user.crm_owner_id is not None and not request.url.path.startswith(
        CRM_MEMBER_PATHS
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Faqat CRM doskasi.")
    return user


def _bearer_user(
    credentials: HTTPAuthorizationCredentials | None, db: Session
) -> User | None:
    subject = (
        tokens.read(credentials.credentials, kind="access") if credentials else None
    )
    try:
        user = db.get(User, uuid.UUID(subject or ""))
    except ValueError:
        return None
    if user is None or not user.is_active:
        return None
    return user


# Async on purpose: a sync dependency runs in a worker thread, and the language
# it sets there never reaches the endpoint. The database read stays threaded.
async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    user = await run_in_threadpool(signed_in, request, credentials, db)
    activate(user.language)
    return user


async def optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """The reader when a valid bearer came with the request, else None."""
    user = await run_in_threadpool(_bearer_user, credentials, db)
    if user is not None:
        activate(user.language)
    return user


def client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def staff_user(user: User = Depends(current_user)) -> User:
    if not user.is_staff:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Faqat xodimlar uchun.")
    return user


Db = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
StaffUser = Annotated[User, Depends(staff_user)]
