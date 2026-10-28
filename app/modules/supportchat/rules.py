"""Two readings of one message that the services and the screen share."""

from datetime import datetime

from app.modules.supportchat.constants import CLIENT, EDIT_WINDOW, OFFICE
from app.modules.supportchat.models import SupportMessage


def side_of(message: SupportMessage) -> str:
    """The client's own words, or the office's - including a reply whose
    staff account has since been erased."""
    return CLIENT if message.sender_id == message.owner_id else OFFICE


def may_change(*, message: SupportMessage, now: datetime) -> bool:
    """Whether the window is still open on this message."""
    return message.deleted_at is None and now - message.created_at <= EDIT_WINDOW
