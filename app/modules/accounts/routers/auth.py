import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, Db, client_address
from app.common import throttle, tokens
from app.common.config import settings
from app.common.db import utcnow
from app.common.routes import reverse
from app.modules.accounts import services
from app.modules.accounts.constants import (
    LOGIN_FAILURES_PER_ADDRESS,
    LOGIN_FAILURES_PER_EMAIL,
    LOGIN_WINDOW_SECONDS,
)
from app.modules.accounts.exceptions import (
    BadCredentials,
    HandoffBlocked,
    HandoffExpired,
    TooManyAttempts,
)
from app.modules.accounts.models import User
from app.modules.accounts.phone import clean_phone
from app.modules.accounts.schemas import (
    HandedOff,
    HandoffIn,
    HandoffOut,
    LoginIn,
    RefreshIn,
    SignupIn,
    TokenPair,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Two counters because they answer different questions: one password tried
# against many accounts is invisible to the per-email count.
LOGIN_BY_EMAIL = "login:email"
LOGIN_BY_ADDRESS = "login:address"


def token_pair(user: User) -> TokenPair:
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
    pair = token_pair(user)
    return SignedUp(
        user=UserOut.model_validate(user),
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


@router.post("/login", response_model=TokenPair)
def login(body: LoginIn, request: Request, db: Db) -> TokenPair:
    """Only failures are counted, and asked about before the hash is paid for.

    A success clears its own account's count, so a morning of typos does not
    lock out the afternoon. The address count is never cleared by a success:
    one valid account would otherwise reset the budget for guessing at every
    other one from the same machine.
    """
    email = body.email.strip().lower()
    address = client_address(request)
    if throttle.spent(
        bucket=LOGIN_BY_EMAIL, key=email, limit=LOGIN_FAILURES_PER_EMAIL
    ) or throttle.spent(
        bucket=LOGIN_BY_ADDRESS, key=address, limit=LOGIN_FAILURES_PER_ADDRESS
    ):
        raise TooManyAttempts
    try:
        user = services.authenticate(db, email=body.email, password=body.password)
    except BadCredentials:
        throttle.record(
            bucket=LOGIN_BY_EMAIL, key=email, window_seconds=LOGIN_WINDOW_SECONDS
        )
        throttle.record(
            bucket=LOGIN_BY_ADDRESS, key=address, window_seconds=LOGIN_WINDOW_SECONDS
        )
        raise
    throttle.forget(bucket=LOGIN_BY_EMAIL, key=email)
    return token_pair(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshIn, db: Db) -> TokenPair:
    subject = tokens.read(body.refresh_token, kind="refresh")
    try:
        user = db.get(User, uuid.UUID(subject or ""))
    except ValueError:
        user = None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Qayta kiring.")
    return token_pair(user)


@router.post("/handoff", response_model=HandoffOut)
def handoff_issue(body: HandoffIn, user: CurrentUser) -> HandoffOut:
    """A five-minute, one-use address that signs the phone's own browser in as
    this account - Meta's login and the payment pages cannot finish inside
    Telegram's WebView. ``next`` must be a cabinet path; anything else lands
    on the cabinet's front page."""
    token = services.issue_handoff(owner=user, destination=body.next)
    path = reverse("accounts:handoff", [token])
    return HandoffOut(url=f"{settings.site_url}{path}")


@router.post("/handoff/{token}", response_model=HandedOff)
def handoff_redeem(token: str, db: Db) -> HandedOff:
    """Spend the address: a token pair and where to land. Spent or expired is
    ``expired``; an account blocked or deleted since the press is ``blocked``."""
    handed = services.redeem_handoff(token=token)
    if handed is None:
        raise HandoffExpired
    try:
        user = db.get(User, uuid.UUID(handed.owner_id))
    except ValueError:
        user = None
    if user is None or not user.is_active:
        raise HandoffBlocked
    pair = token_pair(user)
    return HandedOff(
        next=handed.destination,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )
