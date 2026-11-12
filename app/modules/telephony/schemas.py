import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ConnectIn(BaseModel):
    tenant: str = Field(
        min_length=1,
        max_length=120,
        description="The exchange's name or address: `utc181` or `utc181.utel.uz`.",
    )
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(
        min_length=1,
        max_length=200,
        description="Used once to sign in to UTeL; never kept.",
    )


class ExtensionIn(BaseModel):
    user_id: uuid.UUID | None = Field(
        default=None,
        description="Who answers this number. `null` takes it from its person. "
        "Leave the field out to keep it.",
    )
    softphone: bool | None = Field(
        default=None, description="Calls from the browser. Leave out to keep."
    )


class PhonePersonOut(BaseModel):
    id: str
    name: str
    email: str


class ConnectionOut(BaseModel):
    tenant: str
    api_email: str
    connected_at: datetime
    synced_at: datetime | None = Field(
        description="When the internal numbers were last read from UTeL."
    )
    sip_domain: str
    sip_socket: str
    hook_set_at: datetime | None = Field(
        description="When UTeL was told to send us events. `null`: it was not; "
        "`last_error` says why and «Qayta o'rnatish» tries again."
    )
    last_event_at: datetime | None = Field(
        description="The last event UTeL sent. `null`: none came yet."
    )
    events_last_day: int
    last_error: str
    route_url: str = Field(
        description="Smart routing: paste into UTeL's «Aqlli yo'naltirish» module "
        "as the external address. Secret - show it only on this page."
    )


class ExtensionOut(BaseModel):
    id: str
    number: str = Field(description="The internal number, e.g. `101`.")
    title: str = Field(description="Its name in UTeL.")
    user: PhonePersonOut | None
    softphone: bool
    is_gone: bool = Field(
        description="UTeL no longer has this number; it cannot be given to anybody."
    )
    sip_refused_at: datetime | None = Field(
        description="UTeL refused this number's password to the browser phone, "
        "which is stopped since. Giving the number again or switching the "
        "browser phone clears it; so does a changed password on «Yangilash»."
    )


class TelephonyOut(BaseModel):
    connected: bool
    connection: ConnectionOut | None
    extensions: list[ExtensionOut]
    staff: list[PhonePersonOut] = Field(
        description="Active staff, to choose who answers a number."
    )


class CallOut(BaseModel):
    id: str
    direction: str = Field(description="`in` or `out`.")
    direction_label: str
    answered: bool = Field(description="False: nobody picked up.")
    number: str = Field(description="The other side, `+998901234567`.")
    started_at: datetime
    duration_seconds: int = Field(description="With the ringing.")
    talk_seconds: int = Field(description="The conversation alone.")
    extension: str = Field(description="Our internal number; empty if none took it.")
    staff: PhonePersonOut | None = Field(
        description="Who held that internal number when the call was saved."
    )
    has_recording: bool = Field(
        description="True: `GET /office/telephony/calls/{id}/recording` plays it."
    )


class CallClientOut(BaseModel):
    id: str
    name: str
    email: str
    sales_card_id: str | None
    support_card_id: str | None


class JournalCallOut(CallOut):
    clients: list[CallClientOut] = Field(
        description="Signed-up clients with this number. Empty: a stranger."
    )


class JournalOut(BaseModel):
    total: int
    calls: list[JournalCallOut] = Field(description="Newest first.")


class SipOut(BaseModel):
    socket: str = Field(description="`wss://utc181.utel.uz:8089/ws`.")
    domain: str
    uri: str = Field(description="`sip:101@utc181.utel.uz`.")
    login: str
    password: str = Field(description="Keep in memory only; never store or log.")


class SipRulesOut(BaseModel):
    start_delay_max_seconds: int
    retry_max: int
    retry_base_seconds: int
    retry_step_seconds: int
    retry_jitter_seconds: int
    never_retry_codes: list[int]


class MyPhoneOut(BaseModel):
    enabled: bool = Field(description="False: do not start the browser phone.")
    reason: str = Field(
        description="Why not: `not_connected`, `no_extension`, `softphone_off`, "
        "`sip_refused`. Empty when enabled."
    )
    reason_label: str
    extension: str | None = Field(description="The reader's internal number.")
    sip: SipOut | None
    rules: SipRulesOut = Field(description="How to register and retry.")


class LiveCallOut(BaseModel):
    call_id: str = Field(description="UTeL's id; the same in every event of the call.")
    direction: str
    direction_label: str
    state: str = Field(description="`ringing` or `talking`.")
    number: str
    extension: str = Field(
        description="Incoming: where it rings or who answered. Outgoing: who calls. "
        "May be empty while an incoming call has reached nobody yet."
    )
    staff: PhonePersonOut | None = Field(description="Who holds that number.")
    started_at: datetime
    clients: list[CallClientOut] = Field(description="Empty: a stranger.")


class LiveOut(BaseModel):
    calls: list[LiveCallOut] = Field(description="Going on now, oldest first.")
    busy: list[str] = Field(description="Internal numbers in a conversation.")
