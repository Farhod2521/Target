"""The URLs Telegram posts updates to, one per bot.

Public and unauthenticated, held to one rule: the secret echoed in
``X-Telegram-Bot-Api-Secret-Token`` is compared on every delivery, in
constant time, and an unconfigured deployment refuses everything.

**403 for a bad secret, 200 for everything else.** A non-2xx is what
Telegram retries, and most of what can go wrong here is ours: a body we
could not read, a chat nobody connected. A wrong secret is not Telegram.

**Nothing is done inside the request.** The handler queues and returns,
because acting means calling Telegram back.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from telegramkit import secret_matches

from app.modules.notifications.bot import (
    is_configured,
    staff_bot_configured,
    staff_webhook_secret,
    webhook_secret,
)

logger = logging.getLogger(__name__)
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

webhooks = APIRouter(tags=["webhooks"])


@webhooks.post("/webhooks/telegram/", include_in_schema=False)
async def telegram_webhook(request: Request) -> Response:
    """Check the secret, hand the body to a worker, and answer."""
    from app.modules.notifications.tasks import handle_telegram_update

    if not is_configured() or not secret_matches(
        header=request.headers.get(SECRET_HEADER, ""), expected=webhook_secret()
    ):
        logger.warning("telegram webhook refused: secret did not match")
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    payload = _payload(await request.body())
    if payload:
        handle_telegram_update.delay(payload)
    return JSONResponse({"ok": True})


@webhooks.post("/webhooks/telegram/staff/", include_in_schema=False)
async def staff_telegram_webhook(request: Request) -> Response:
    """The staff bot's: the same checks, its own secret and worker."""
    from app.modules.notifications.tasks import handle_staff_telegram_update

    if not staff_bot_configured() or not secret_matches(
        header=request.headers.get(SECRET_HEADER, ""), expected=staff_webhook_secret()
    ):
        logger.warning("staff telegram webhook refused: secret did not match")
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    payload = _payload(await request.body())
    if payload:
        handle_staff_telegram_update.delay(payload)
    return JSONResponse({"ok": True})


def _payload(body: bytes) -> dict[str, Any]:
    """The body as a dict, or an empty one: a command or a press is
    something the person can repeat, so a body we cannot read is dropped."""
    try:
        parsed = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        logger.warning("telegram webhook: body was not JSON")
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = ["SECRET_HEADER", "webhooks"]
