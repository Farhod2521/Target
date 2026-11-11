"""The support chat telling the one chat that a message was stored or
changed, so a person's reply shows in the client's thread. Both run inside
the support message's own transaction: the thread's row is in the same
commit, never late and never twice (``services/support.py``)."""

from typing import Any

from app.common.db import utcnow
from app.common.hooks import on
from app.modules.supportchat.services import MESSAGE_CHANGED, MESSAGE_STORED


@on(MESSAGE_STORED)
def support_message_stored(*, db: Any, message: Any, **_: Any) -> None:
    from app.modules.assistant.services.support import on_stored

    on_stored(db, message=message, now=utcnow())


@on(MESSAGE_CHANGED)
def support_message_changed(*, db: Any, message: Any, **_: Any) -> None:
    from app.modules.assistant.services.support import on_changed

    on_changed(db, message=message)
