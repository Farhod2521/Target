"""A member of staff's own link to the staff bot, as JSON.

Open to every office role: what arrives follows the roles, so a role with nothing
to receive reads an empty list.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import Db
from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ANSWER_ROLES, FAULT_ROLES, Role
from app.modules.backoffice.permissions import roles_of, staff_required
from app.modules.backoffice.schemas import MessageOut, StaffBotOut, StaffBotUrlOut
from app.modules.notifications.bot import staff_bot_configured
from app.modules.notifications.models import StaffChat
from app.modules.notifications.services import (
    staff_link_of,
    staff_link_url,
    unlink_staff_chat,
)

router = APIRouter(prefix="/telegram")
Staff = Annotated[User, Depends(staff_required(*Role))]
TOPICS: tuple[tuple[str, tuple[Role, ...]], ...] = (
    ("support", ANSWER_ROLES),
    ("faults", FAULT_ROLES),
)


def _link_out(chat: StaffChat | None) -> dict[str, Any] | None:
    if chat is None:
        return None
    return {
        "account": f"@{chat.username}" if chat.username else chat.chat_id,
        "linked_at": chat.linked_at,
    }


@router.get("", responses={200: {"model": StaffBotOut}})
def status(db: Db, user: Staff) -> dict[str, Any]:
    """Whether this person is linked, and what the bot would bring them."""
    held = roles_of(db, user)
    username = settings.staff_bot_username
    return {
        "configured": staff_bot_configured(),
        "username": f"@{username}" if username else "",
        "link": _link_out(staff_link_of(db, owner=user)),
        "roles": [str(role) for role in Role if str(role) in held],
        "topics": [
            {"topic": topic, "roles": [str(role) for role in roles]}
            for topic, roles in TOPICS
            if held & {str(role) for role in roles}
        ],
    }


@router.post("/link", responses={200: {"model": StaffBotUrlOut}})
def link(db: Db, user: Staff) -> dict[str, str]:
    """The bot's address with a fresh one-time code; /start there spends it."""
    return {"url": staff_link_url(db, owner=user)}


@router.post("/unlink", responses={200: {"model": MessageOut}})
def unlink(db: Db, user: Staff) -> dict[str, str]:
    unlink_staff_chat(db, owner=user)
    db.commit()
    return {"message": "Telegram uzildi."}
