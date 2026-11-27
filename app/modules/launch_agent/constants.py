from typing import Final

from app.common.choices import Choices


class SessionStatus(Choices):
    # Still asking.
    OPEN = "open"
    # Everything said and saved on the launch: pictures are next.
    READY = "ready"
    # Left for another conversation, or its launch was made or dropped.
    CLOSED = "closed"


class Author:
    USER = "user"
    AGENT = "agent"


MAX_TEXT_CHARS: Final = 1000
# One conversation: past this the person is sent to the screens.
MAX_TURNS: Final = 40
# Messages worked out by the model, per person a day - a press costs none.
HEARD_PER_DAY: Final = 80
HEARD_BUCKET: Final = "launch_agent_heard"
PROMPT: Final = "launch_agent_hear"
RELATED_TYPE: Final = "launch_agent_session"
NEXT_MEDIA: Final = "media"
MESSAGES_KEPT: Final = 80
# A spoken message: its size, how long the provider is waited for, and how
# many a person may send a day.
VOICE_MAX_BYTES: Final = 10 * 1024 * 1024
VOICE_TIMEOUT_SECONDS: Final = 30.0
VOICE_PER_DAY: Final = 60
VOICE_BUCKET: Final = "launch_agent_voice"
VOICE_LANGUAGES: Final = ("uz", "ru", "en")

__all__ = [
    "HEARD_BUCKET",
    "HEARD_PER_DAY",
    "MAX_TEXT_CHARS",
    "MAX_TURNS",
    "MESSAGES_KEPT",
    "NEXT_MEDIA",
    "PROMPT",
    "RELATED_TYPE",
    "VOICE_BUCKET",
    "VOICE_LANGUAGES",
    "VOICE_MAX_BYTES",
    "VOICE_PER_DAY",
    "VOICE_TIMEOUT_SECONDS",
    "Author",
    "SessionStatus",
]
