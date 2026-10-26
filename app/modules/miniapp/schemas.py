"""Response shapes for the Telegram mini app's entry, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from pydantic import BaseModel, Field


class EntryOut(BaseModel):
    next_url: str = Field(description="Where to go once signed in; a cabinet path.")
    bridge_script: str
    next_field: str


class AuthOut(BaseModel):
    ok: bool | None = Field(None, description="Present when signed in.")
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    in_telegram: bool | None = None
    error: str | None = Field(None, description="Present instead when refused.")
    message: str | None = None


__all__ = ["AuthOut", "EntryOut"]
