from app.common.routes import reverse
from app.modules.notifications.services.compose import Message, _bold, _link, escaped


def lapse_stopped_message() -> Message:
    lines = [
        _bold("Obuna muddati tugadi"),
        "",
        escaped("Platformada yaratilgan reklamalaringiz to'xtatildi."),
        escaped(
            "To'lov qilib obunani davom ettirishingiz mumkin - reklamalar o'zi qayta yoqiladi."
        ),
        "",
        _link(path=reverse("billing:plans"), label="Obunani yangilash"),
    ]
    return Message(text="\n".join(lines))


def lapse_cut_off_message() -> Message:
    lines = [
        _bold("Obuna yangilanmadi"),
        "",
        escaped(
            "Obuna tugaganiga 72 soat bo'ldi. Reklamalaringiz o'chirilmaydi, to'xtatilgan holda saqlanadi. Yangi lidlar va raqamlar endi yig'ilmaydi."
        ),
        escaped(
            "To'lov qilib obunani davom ettirishingiz mumkin - reklamalar o'zi qayta yoqiladi."
        ),
        "",
        _link(path=reverse("billing:plans"), label="Obunani yangilash"),
    ]
    return Message(text="\n".join(lines))


def unfrozen_message(*, until: str) -> Message:
    lines = [
        _bold("Obuna muzlatishdan chiqdi"),
        "",
        escaped(
            "Obunangiz yana ishlayapti. Muzlatilgan kunlar sarflanmadi: obuna %(until)s gacha amal qiladi."
            % {"until": until}
        ),
        escaped("To'xtatilgan reklamalaringiz o'zi qayta yoqiladi."),
        "",
        _link(path=reverse("billing:plans"), label="Obunani ko'rish"),
    ]
    return Message(text="\n".join(lines))


__all__ = ["lapse_cut_off_message", "lapse_stopped_message", "unfrozen_message"]
