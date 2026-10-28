"""What one press of Send carries, before it is a message."""

from dataclasses import dataclass

from fastapi import UploadFile


@dataclass(frozen=True, slots=True)
class Voice:
    """A recording made in the browser, and how long the page measured it."""

    upload: UploadFile
    seconds: int


@dataclass(frozen=True, slots=True)
class Draft:
    """One message to be stored. A voice and a sticker each stand alone."""

    body: str = ""
    files: tuple[UploadFile, ...] = ()
    voice: Voice | None = None
    sticker: str = ""
    # The id of the message this one answers, as the composer sent it.
    reply_to: str = ""
