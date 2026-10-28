"""One message in a line of words, for places that cannot draw it."""

from app.modules.supportchat.constants import MessageKind, sticker_emoji
from app.modules.supportchat.models import SupportAttachment, SupportMessage


def preview_text(message: SupportMessage, files: list[SupportAttachment]) -> str:
    """The message's words, or what stands in for them."""
    if message.deleted_at is not None:
        return "Xabar o'chirildi"
    if message.kind == MessageKind.STICKER:
        return sticker_emoji(message.sticker) or "Stiker"
    if message.kind == MessageKind.VOICE:
        return voice_label(seconds=files[0].duration_seconds if files else 0)
    if message.body:
        return message.body
    return files_label(message=message, files=files)


def files_label(*, message: SupportMessage, files: list[SupportAttachment]) -> str:
    """ "Fayl: name", or how many when there are several."""
    count = len(files) or (1 if message.original_name else 0)
    if count > 1:
        return f"{count} ta fayl"
    return f"Fayl: {message.original_name}" if count else ""


def voice_label(*, seconds: int) -> str:
    """ "Ovozli xabar (0:42)"."""
    return f"Ovozli xabar ({clock(seconds)})"


def clock(seconds: int) -> str:
    """Seconds as m:ss."""
    return f"{seconds // 60}:{seconds % 60:02d}"
