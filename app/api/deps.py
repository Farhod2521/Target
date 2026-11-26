import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.acting import Acting, act
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


# A request may name the business it works in. For the owner that pins the
# business's page and account for the request (``app.common.acting``). For a
# member it opens these paths, and only these, on that business: the request
# then runs as the owner, on the business's pair, if the member's grants over
# its adverts allow it - «ko'rish» to read, «o'zgartirish» for anything else.
BUSINESS_HEADER = "x-business"
MEMBER_BUSINESS_PATHS = (
    "/api/v1/campaigns",
    "/api/v2/campaigns",
    "/api/v1/launch",
    "/api/v1/metrics",
)
READING_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def business_scope(
    request: Request, db: Session, user: User
) -> tuple[User, Acting] | None:
    """Who the request runs as and on which business, when it names one.

    ``None`` when it names none, or a member names one on a path that is not
    a business's to open (their CRM board is theirs under their own login).
    Raises as :func:`access_for` does for a business that is not theirs.
    """
    from metaads import PROVIDER
    from sqlalchemy import select

    from app.modules.businesses.constants import GrantArea, GrantLevel, LinkKind
    from app.modules.businesses.exceptions import NoAccess, UnknownBusiness
    from app.modules.businesses.models import BusinessLink
    from app.modules.businesses.selectors.access import access_for

    named = request.headers.get(BUSINESS_HEADER, "").strip()
    if not named:
        return None
    member = user.crm_owner_id is not None
    if member and not request.url.path.startswith(MEMBER_BUSINESS_PATHS):
        return None
    try:
        business_id = uuid.UUID(named)
    except ValueError:
        raise UnknownBusiness from None
    access = access_for(db, business_id=business_id, user=user)
    link = db.scalar(
        select(BusinessLink).where(
            BusinessLink.business_id == business_id,
            BusinessLink.kind == LinkKind.META_PAIR,
            BusinessLink.unbound_at.is_(None),
        )
    )
    held = Acting(
        business_id=business_id,
        owner_id=access.business.user_id,
        actor_id=user.id,
        page_id=link.page_id if link is not None else None,
        ad_account_id=link.ad_account_id if link is not None else None,
    )
    if access.is_owner:
        return user, held
    level = GrantLevel.VIEW if request.method in READING_METHODS else GrantLevel.EDIT
    if not access.may(GrantArea.ADS, PROVIDER, level):
        raise NoAccess
    owner = db.get(User, access.business.user_id)
    if owner is None or not owner.is_active:
        raise UnknownBusiness
    return owner, held


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
    scoped = business_scope(request, db, user)
    if scoped is not None:
        request.state.acting = scoped[1]
        request.state.actor_language = user.language
        return scoped[0]
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
    # Set here, not in the thread above, for the same reason as the language.
    act(getattr(request.state, "acting", None))
    if not user.country:
        await run_in_threadpool(_place, request, user, db)
    activate(getattr(request.state, "actor_language", None) or user.language)
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
