import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import get_db
from app.common.i18n import activate
from app.modules.accounts.models import User

_bearer = HTTPBearer(auto_error=False)


# ``/api/v3/businesses`` is open to a member's login because every route of
# it asks what that person may do in the business they name.
CRM_MEMBER_PATHS = (
    "/api/v1/crm",
    "/api/v1/auth",
    "/api/v1/account/language",
    "/api/v3/businesses",
)
# Read only: a manager's login may say who it is (name, language, whose
# board), and nothing else under /account - saving a phone there would hand
# the owner's call-back cards to the manager.
CRM_MEMBER_READS = ("/api/v1/account",)


def crm_member_may(request: Request) -> bool:
    path = request.url.path
    if path.startswith(CRM_MEMBER_PATHS):
        return True
    return request.method == "GET" and path.rstrip("/") in CRM_MEMBER_READS


def may_sign_in(db: Session, user: User | None) -> bool:
    """Active, and a CRM login stands or falls with the account that made it."""
    if user is None or not user.is_active:
        return False
    if user.crm_owner_id is None:
        return True
    owner = db.get(User, user.crm_owner_id)
    return owner is not None and owner.is_active


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
    if not may_sign_in(db, user):
        raise refused
    if user.crm_owner_id is not None and not crm_member_may(request):
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
    if not may_sign_in(db, user):
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
    if not user.country:
        await run_in_threadpool(_place, request, user, db)
    activate(user.language)
    return user


def _place(request: Request, user: User, db: Session) -> None:
    """The account's country, once, from the address it first comes from.

    It decides the plans' currency (so'm in Uzbekistan, dollars elsewhere)
    and is not changed by later visits; the office may change it.
    """
    from app.common.geo import country_of

    code = country_of(headers=request.headers, address=client_address(request))
    if len(code) != 2:
        return
    db.execute(
        update(User).where(User.id == user.id, User.country == "").values(country=code)
    )
    # The commit expires the row: the next read of user.country loads it.
    db.commit()


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
