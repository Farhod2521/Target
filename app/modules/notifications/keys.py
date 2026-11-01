import hashlib
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Final
from uuid import UUID

from app.modules.notifications.constants import (
    CALLBACK_ANSWER,
    CALLBACK_APPROVE,
    CALLBACK_DAILY_LIST,
    CALLBACK_DAILY_PAIR,
    CALLBACK_FREQUENCY_FINE,
    CALLBACK_PAUSE,
    CALLBACK_PAUSE_ANYWAY,
    CALLBACK_REJECT,
    CALLBACK_REPLY,
    CALLBACK_SEPARATOR,
    CALLBACK_SUPPORT_DROP,
    CALLBACK_SUPPORT_SEND,
    CALLBACK_SURVEY,
    CALLBACK_WAIT,
    CALLBACK_WATCH_DELETE,
    CALLBACK_WATCH_DELETE_SURE,
    CALLBACK_WATCH_DOWN,
    CALLBACK_WATCH_PAUSE,
    CALLBACK_WATCH_RESUME,
    CALLBACK_WATCH_UP,
    CALLBACK_WATCH_WAIT,
    CALLBACK_WEEKLY_LIST,
    CALLBACK_WEEKLY_PAIR,
    DAILY_PAIR_DIGEST_CHARS,
    REJECTION_DIGEST_CHARS,
)

PAUSE_ACTIONS: Final = frozenset({CALLBACK_PAUSE, CALLBACK_PAUSE_ANYWAY, CALLBACK_WAIT})
WATCH_ACTIONS: Final = frozenset(
    {
        CALLBACK_WATCH_UP,
        CALLBACK_WATCH_DOWN,
        CALLBACK_WATCH_PAUSE,
        CALLBACK_WATCH_DELETE,
        CALLBACK_WATCH_DELETE_SURE,
        CALLBACK_WATCH_WAIT,
        CALLBACK_WATCH_RESUME,
    }
)
ACTIONS: Final = frozenset(
    {
        CALLBACK_ANSWER,
        CALLBACK_APPROVE,
        CALLBACK_REJECT,
        CALLBACK_FREQUENCY_FINE,
        *PAUSE_ACTIONS,
        *WATCH_ACTIONS,
    }
)
_EXTERNAL_ID: Final = re.compile("[A-Za-z0-9_-]+")
MAX_EXTERNAL_ID_CHARS: Final = 32


def suggestion_subject(*, pk: Any) -> str:
    return str(pk)


def weekly_done_subject(*, since: date) -> str:
    return f"week:{since.isoformat()}"


def weekly_subject(*, since: date) -> str:
    """The week's one message."""
    return f"week:{since.isoformat()}:list"


def weekly_final_subject(*, since: date) -> str:
    """The week's message carries the finished figures."""
    return f"week:{since.isoformat()}:final"


def daily_subject(*, day: date, part: int) -> str:
    """One message of a day's list, sent once - Django's subject, so a day
    it already sent is not sent again."""
    return f"{day.isoformat()}:list:{part}"


def daily_done_subject(*, day: date) -> str:
    return day.isoformat()


def daily_final_subject(*, day: date) -> str:
    """The day's message carries the night's finished figures."""
    return f"{day.isoformat()}:final"


def expiry_subject(*, expires_at: datetime, days: int) -> str:
    return f"{expires_at.strftime('%Y-%m-%d')}:{days}"


def lapse_subject(*, hold_id: Any, step: str) -> str:
    return f"lapse:{hold_id}:{step}"


def connection_subject(*, connection_id: Any, status: str, now: datetime) -> str:
    return f"{connection_id}:{status}:{now.strftime('%Y-%m-%d')}"


def action_required_subject(*, connection_id: Any, since: datetime) -> str:
    return f"{connection_id}:hold:{since.isoformat()}"


def rejection_subject(*, external_id: str, feedback: Mapping[str, Any]) -> str:
    canonical = repr(sorted(_flatten(feedback)))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{external_id}:{digest[:REJECTION_DIGEST_CHARS]}"


def _flatten(feedback: Mapping[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    overall = feedback.get("overall")
    if isinstance(overall, Mapping):
        pairs += [(str(key), str(value)) for key, value in overall.items()]
    by_placement = feedback.get("by_placement")
    if isinstance(by_placement, Mapping):
        for surface, entries in by_placement.items():
            if isinstance(entries, Mapping):
                pairs += [
                    (f"{surface}/{key}", str(value)) for key, value in entries.items()
                ]
    return pairs


def press_data(*, action: str, pk: Any) -> str:
    return f"{action}{CALLBACK_SEPARATOR}{pk}"


def pause_data(*, external_id: str, action: str = CALLBACK_PAUSE) -> str:
    return f"{action}{CALLBACK_SEPARATOR}{external_id}"


def read_press(data: str) -> tuple[str, str] | None:
    action, separator, identifier = data.partition(CALLBACK_SEPARATOR)
    if not separator or action not in ACTIONS or (not identifier):
        return None
    if action in PAUSE_ACTIONS or action in WATCH_ACTIONS:
        if len(identifier) <= MAX_EXTERNAL_ID_CHARS and _EXTERNAL_ID.fullmatch(
            identifier
        ):
            return (action, identifier)
        return None
    try:
        UUID(identifier)
    except ValueError:
        return None
    return (action, identifier)


def outcome_subject(*, pk: Any) -> str:
    return f"outcome:{pk}"


def reply_press_data(*, message_id: Any, index: int) -> str:
    return (
        f"{CALLBACK_REPLY}{CALLBACK_SEPARATOR}{message_id}{CALLBACK_SEPARATOR}{index}"
    )


def read_reply_press(data: str) -> tuple[str, int] | None:
    action, separator, rest = data.partition(CALLBACK_SEPARATOR)
    if action != CALLBACK_REPLY or not separator:
        return None
    message_id, separator, place = rest.partition(CALLBACK_SEPARATOR)
    if not separator or not place.isdigit():
        return None
    try:
        UUID(message_id)
    except ValueError:
        return None
    return (message_id, int(place))


def support_press_data(*, send: bool, token: str) -> str:
    action = CALLBACK_SUPPORT_SEND if send else CALLBACK_SUPPORT_DROP
    return f"{action}{CALLBACK_SEPARATOR}{token}"


def read_support_press(data: str) -> tuple[bool, str] | None:
    action, separator, token = data.partition(CALLBACK_SEPARATOR)
    if not separator or not token or (not _EXTERNAL_ID.fullmatch(token)):
        return None
    if action == CALLBACK_SUPPORT_SEND:
        return (True, token)
    if action == CALLBACK_SUPPORT_DROP:
        return (False, token)
    return None


SURVEY_ACTIONS: Final = frozenset({"o", "t", "d", "n", "s", "l"})


def survey_press_data(*, step: int, action: str, value: int = 0) -> str:
    sep = CALLBACK_SEPARATOR
    return f"{CALLBACK_SURVEY}{sep}{step}{sep}{action}{sep}{value}"


def read_survey_press(data: str) -> tuple[int, str, int] | None:
    parts = data.split(CALLBACK_SEPARATOR)
    if len(parts) != 4 or parts[0] != CALLBACK_SURVEY:
        return None
    _prefix, step, action, value = parts
    if action not in SURVEY_ACTIONS or not step.isdigit() or (not value.isdigit()):
        return None
    return (int(step), action, int(value))


LIST_PRESSES: Final = (CALLBACK_DAILY_LIST, CALLBACK_WEEKLY_LIST)
PAIR_PRESSES: Final = (CALLBACK_DAILY_PAIR, CALLBACK_WEEKLY_PAIR)
_DIGEST: Final = re.compile(rf"[0-9a-f]{{{DAILY_PAIR_DIGEST_CHARS}}}")


def pair_digest(pair: str) -> str:
    """A pair key short enough for a button."""
    return hashlib.sha256(pair.encode("utf-8")).hexdigest()[:DAILY_PAIR_DIGEST_CHARS]


def daily_pair_data(*, day: date, pair: str) -> str:
    """A pair's button under the daily message: ``dd:<day>:<pair digest>``."""
    sep = CALLBACK_SEPARATOR
    return f"{CALLBACK_DAILY_PAIR}{sep}{day:%Y%m%d}{sep}{pair_digest(pair)}"


def daily_list_data(*, day: date, part: int) -> str:
    """«Back to the list»: ``dl:<day>:<which message>``."""
    sep = CALLBACK_SEPARATOR
    return f"{CALLBACK_DAILY_LIST}{sep}{day:%Y%m%d}{sep}{part}"


def weekly_pair_data(*, since: date, pair: str) -> str:
    """A pair's button under the weekly message: ``wd:<Monday>:<pair digest>``."""
    sep = CALLBACK_SEPARATOR
    return f"{CALLBACK_WEEKLY_PAIR}{sep}{since:%Y%m%d}{sep}{pair_digest(pair)}"


def weekly_list_data(*, since: date) -> str:
    """«Back to the list»: ``wl:<Monday>:0``."""
    sep = CALLBACK_SEPARATOR
    return f"{CALLBACK_WEEKLY_LIST}{sep}{since:%Y%m%d}{sep}0"


def read_daily_press(data: str) -> tuple[str, date, str] | None:
    """``(action, first day, pair digest or part)``, or None. Strict: callback
    data is whatever the sender put in it."""
    parts = data.split(CALLBACK_SEPARATOR)
    if len(parts) != 3 or parts[0] not in (*LIST_PRESSES, *PAIR_PRESSES):
        return None
    action, day_text, value = parts
    try:
        day = datetime.strptime(day_text, "%Y%m%d").date()
    except ValueError:
        return None
    if action in LIST_PRESSES and value.isdigit():
        return action, day, value
    if action in PAIR_PRESSES and _DIGEST.fullmatch(value):
        return action, day, value
    return None


__all__ = [
    "ACTIONS",
    "SURVEY_ACTIONS",
    "WATCH_ACTIONS",
    "connection_subject",
    "daily_done_subject",
    "daily_list_data",
    "daily_pair_data",
    "daily_subject",
    "outcome_subject",
    "pair_digest",
    "pause_data",
    "press_data",
    "read_daily_press",
    "read_press",
    "read_reply_press",
    "read_support_press",
    "read_survey_press",
    "rejection_subject",
    "reply_press_data",
    "suggestion_subject",
    "support_press_data",
    "survey_press_data",
    "weekly_done_subject",
]
