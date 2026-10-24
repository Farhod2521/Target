from app.common.routes import reverse
from app.modules.notifications.services.compose import Message, _bold, _link, escaped


def lapse_stopped_message(*, until: str) -> Message:
    lines = [
        _bold("Obuna muddati tugadi"),
        "",
        escaped("Platformada yaratilgan reklamalaringiz to'xtatildi."),
        escaped(
            "%(until)s gacha to'lov qilsangiz, ular o'zi qayta yoqiladi. Aks holda reklamalar butunlay o'chiriladi."
            % {"until": until}
        ),
        "",
        _link(path=reverse("billing:plans"), label="Obunani yangilash"),
    ]
    return Message(text="\n".join(lines))


def lapse_last_warning_message(*, until: str) -> Message:
    lines = [
        _bold("Ertaga reklamalaringiz o'chiriladi"),
        "",
        escaped(
            "Obuna yangilanmagani uchun platformada yaratilgan reklamalaringiz %(until)s da butunlay o'chiriladi. Hozir to'lasangiz, ular qayta yoqiladi."
            % {"until": until}
        ),
        "",
        _link(path=reverse("billing:plans"), label="Obunani yangilash"),
    ]
    return Message(text="\n".join(lines))


__all__ = ["lapse_last_warning_message", "lapse_stopped_message"]
