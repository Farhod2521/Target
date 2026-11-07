from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import Db, client_address
from app.common import throttle
from app.common.config import settings
from app.modules.accounts.constants import (
    SIGNUP_WINDOW_SECONDS,
    SIGNUPS_PER_ADDRESS,
    SOCIAL_STATE_TTL_SECONDS,
    SocialProvider,
)
from app.modules.accounts.phone import clean_phone
from app.modules.accounts.routers.auth import SIGNUP_BUCKET, token_pair
from app.modules.accounts.schemas import (
    HandedOff,
    SocialCompleteIn,
    SocialPendingOut,
    SocialProvidersOut,
    SocialStartIn,
    SocialStartOut,
)
from app.modules.accounts.services import social_login

router = APIRouter(prefix="/auth/social", tags=["auth"])


@router.get("", response_model=SocialProvidersOut)
def providers() -> SocialProvidersOut:
    """The «Google» button is drawn only when this lists it."""
    return SocialProvidersOut(providers=social_login.providers())


@router.get("/finish/{token}", response_model=SocialPendingOut)
def finish_form(token: str) -> SocialPendingOut:
    """/accounts/social/<token>/ asks this before drawing the form; a dead
    token is ``social_expired`` (410): press Google again."""
    held = social_login.pending(token=token)
    return SocialPendingOut(
        provider=held.provider,
        email=held.email,
        full_name=held.full_name,
        needs_email=not held.email,
        phone=held.phone,
    )


@router.post("/finish/{token}", response_model=HandedOff)
def finish_signup(
    token: str, body: SocialCompleteIn, request: Request, db: Db
) -> HandedOff:
    """The phone and the role (and the email, from Telegram): the account
    is opened and signed in.

    A number another account holds is ``phone_taken`` under ``phone``; a
    typed address another account holds is ``email_in_use`` under ``email``.
    The token survives both, so the form can be corrected and sent again.
    """
    if not throttle.hit(
        bucket=SIGNUP_BUCKET,
        key=client_address(request),
        limit=SIGNUPS_PER_ADDRESS,
        window_seconds=SIGNUP_WINDOW_SECONDS,
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring.",
        )
    user, landing = social_login.complete(
        db,
        token=token,
        phone=clean_phone(body.phone),
        role=body.role.value,
        full_name=body.full_name.strip(),
        email=str(body.email or ""),
        address=client_address(request),
    )
    pair = token_pair(user)
    return HandedOff(
        next=landing,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


# Each press keeps a state for a quarter hour; nobody presses Google this often.
STARTS_PER_ADDRESS = 60
START_BUCKET = "social:start:address"


@router.post("/{provider}/start", response_model=SocialStartOut)
def start(
    provider: SocialProvider, body: SocialStartIn, request: Request
) -> SocialStartOut:
    """Sign in or sign up: send the browser to ``url``. It comes back to the
    cabinet on its own - see the callback."""
    if not throttle.hit(
        bucket=START_BUCKET,
        key=client_address(request),
        limit=STARTS_PER_ADDRESS,
        window_seconds=SOCIAL_STATE_TTL_SECONDS,
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring.",
        )
    url = social_login.start(
        provider=provider.value,
        next_path=body.next,
        referral_code=body.referral_code,
        language=body.language.value if body.language else "",
    )
    return SocialStartOut(url=url)


@router.get("/{provider}/callback", include_in_schema=False)
def callback(
    provider: SocialProvider,
    request: Request,
    db: Db,
    state: str = "",
    code: str = "",
    error: str = "",
) -> RedirectResponse:
    """Google and Telegram send the browser here; it leaves for one of:

    - ``/accounts/handoff/<token>/`` - signed in (the handoff page spends it);
    - ``/accounts/social/<token>/`` - somebody new: phone and role first;
    - ``/accounts/login/?social_error=<why>`` - refused;
    - Settings with ``?linked=<provider>`` or ``?social_error=<why>`` - tying one.
    """
    path = social_login.finish(
        db,
        provider=provider.value,
        state=state,
        code=code,
        error=error,
        address=client_address(request),
    )
    return RedirectResponse(f"{settings.site_url}{path}", status_code=302)
