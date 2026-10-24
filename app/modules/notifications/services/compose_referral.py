from collections.abc import Sequence

from app.modules.accounts.models import User
from app.modules.notifications.services.compose import Message, _bold, escaped


def invitee_name(*, invited: User, username: str) -> str:
    if username:
        return f"@{username}"
    parts = invited.full_name.split()
    if not parts:
        return "yangi foydalanuvchi"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[1][0].upper()}."


def referral_message(*, name: str, rewards: Sequence[tuple[str, str]]) -> Message:
    lines = [
        _bold("🎉 " + "Yangi do'st qo'shildi!"),
        "",
        escaped(
            "Sizning havolangiz orqali %(name)s ro'yxatdan o'tdi." % {"name": name}
        ),
    ]
    if rewards:
        lines += ["", escaped("U birinchi to'lovni qilsa, balansingizga tushadi:")]
        lines += [escaped(f"• {plan} — {bonus}") for plan, bonus in rewards]
    return Message(text="\n".join(lines))
