"""The cabinet opened inside Telegram: a signed launch traded for a token pair."""

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import Db
from app.common import tokens
from app.common.db import utcnow
from app.common.routes import reverse
from app.modules.miniapp.constants import BRIDGE_SCRIPT, NEXT_FIELD
from app.modules.miniapp.exceptions import MiniAppRefused
from app.modules.miniapp.services import authenticate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/miniapp", tags=["miniapp"])


def safe_next(asked: str) -> str:
    home = reverse("metrics:dashboard")
    door = reverse("miniapp:entry").rstrip("/")
    if (
        asked.startswith(door)
        or asked.startswith("//")
        or asked.startswith("/\\")
        or ".." in asked
        or not asked.startswith(home)
    ):
        return home
    return asked


@router.get("/entry")
def entry(next: str = "") -> dict[str, Any]:
    return {
        "next_url": safe_next(next),
        "bridge_script": BRIDGE_SCRIPT,
        "next_field": NEXT_FIELD,
    }


class AuthIn(BaseModel):
    init_data: str = ""


@router.post("/auth")
def auth(body: AuthIn, db: Db) -> dict[str, Any]:
    now = utcnow()
    try:
        user = authenticate(db, init_data=body.init_data, now=now)
    except MiniAppRefused as exc:
        return {"error": exc.code, "message": exc.message}
    logger.info("miniapp_opened", extra={"owner": str(user.id)})
    return {
        "ok": True,
        "access_token": tokens.issue(subject=str(user.id), kind="access", now=now),
        "refresh_token": tokens.issue(subject=str(user.id), kind="refresh", now=now),
        "token_type": "bearer",
        "in_telegram": True,
    }
