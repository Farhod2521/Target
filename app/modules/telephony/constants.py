import re
from typing import Final

from app.common.choices import Choices


class Provider(Choices):
    UTEL = "utel"


# A UTeL tenant is the first label of its address: ``utc181`` in
# ``utc181.utel.uz``. Only this shape is ever put into a URL we call.
TENANT_SHAPE: Final = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
UTEL_ZONE: Final = "utel.uz"
# The path matters: the bare port answers 200 and speaks no SIP.
SIP_SOCKET: Final = "wss://{tenant}.utel.uz:8089/ws"
HOOK_PATH: Final = "/webhooks/utel/{key}"
HOOK_KEY_BYTES: Final = 32
# Every event the exchange can send; each is a flag on the hook.
HOOK_EVENTS: Final = (
    "call_started",
    "call_ended",
    "dial_started",
    "dial_answered",
    "dial_ended",
    "call_transferred",
    "call_saved",
)
CALL_SAVED: Final = "call_saved"
# What one event may weigh. A real one is a few kilobytes.
HOOK_BODY_MAX: Final = 256 * 1024
EVENT_NAME_MAX: Final = 40
CALL_ID_MAX: Final = 64
NUMBER_MAX: Final = 16
TITLE_MAX: Final = 60
ERROR_MAX: Final = 300


class Direction(Choices):
    IN = "in"
    OUT = "out"


DIRECTION_LABELS: Final = {Direction.IN: "Kiruvchi", Direction.OUT: "Chiquvchi"}


class CallScope(Choices):
    ALL = "all"
    # The number is a signed-up client's.
    KNOWN = "known"
    # Nobody signed up with this number: the journal of strangers.
    UNKNOWN = "unknown"


# The exchange's clock; its times come without a zone.
EXCHANGE_ZONE: Final = "Asia/Tashkent"
COUNTRY_PREFIX: Final = "998"
LOCAL_DIGITS: Final = 9
# An internal number: users are 100-4999, groups and menus up to 6199.
EXTENSION_DIGITS_MAX: Final = 4
PHONE_MAX: Final = 20
LINE_MAX: Final = 20
URL_MAX: Final = 500
# What the hourly read looks back over, and what the first one does.
BACKFILL_HOURS: Final = 3
FIRST_BACKFILL_DAYS: Final = 30
BACKFILL_PAGES_MAX: Final = 40
# Raw events are for looking into a fault; the calls are kept apart.
HOOK_EVENTS_KEEP_DAYS: Final = 14
CARD_CALLS: Final = 50
CALLS_PAGE: Final = 50
CALLS_PAGE_MAX: Final = 100
CALL_SEARCH_MAX: Final = 20
RECORDING_MAX_BYTES: Final = 200 * 1024 * 1024
RECORDING_TIMEOUT_SECONDS: Final = 60.0
