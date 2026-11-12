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
# What one event may weigh. A real one is a few kilobytes.
HOOK_BODY_MAX: Final = 256 * 1024
EVENT_NAME_MAX: Final = 40
CALL_ID_MAX: Final = 64
NUMBER_MAX: Final = 16
TITLE_MAX: Final = 60
ERROR_MAX: Final = 300
