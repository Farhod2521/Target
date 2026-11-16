"""What the guard's messages say, in the reader's language: uz, ru, en.

Fixed sentences with the name, the price and the figures put in. No model
writes or translates anything here: a finding picks its sentences by kind
and action, and :func:`app.common.i18n.get_language` picks the language.
The cabinet's line and the phone's message are the same words.
"""

from typing import Any, Final

from app.common.i18n import DEFAULT, get_language
from app.common.money import format_minor
from app.modules.agent.models import GuardAlert
from core.metrics import formulas
from core.metrics.arithmetic import basis_points_or_none

# What one result is called, by the group's result.
WORDS: Final[dict[str, dict[str, str]]] = {
    "uz": {
        "lead": "lid",
        "chat": "suhbat",
        "call": "qo'ng'iroq",
        "click": "o'tish",
        "profile": "profilga o'tish",
    },
    "ru": {
        "lead": "лид",
        "chat": "переписка",
        "call": "звонок",
        "click": "переход",
        "profile": "переход в профиль",
    },
    "en": {
        "lead": "lead",
        "chat": "conversation",
        "call": "call",
        "click": "click",
        "profile": "profile visit",
    },
}

# The buttons, by what pressing one does.
BUTTONS: Final[dict[str, dict[str, str]]] = {
    "uz": {
        "pause": "To'xtatish",
        "budget_down": "Byudjetni 20% kamaytirish",
        "leave": "Hozircha tegmaslik",
        "resume": "Qayta yoqish",
        "keep_off": "Shunday qolsin",
        "pause_ad": "Shu reklamani to'xtatish",
        "add_creative": "Kreativ qo'shish",
    },
    "ru": {
        "pause": "Остановить",
        "budget_down": "Снизить бюджет на 20%",
        "leave": "Пока не трогать",
        "resume": "Включить снова",
        "keep_off": "Оставить выключенной",
        "pause_ad": "Остановить это объявление",
        "add_creative": "Добавить креатив",
    },
    "en": {
        "pause": "Pause",
        "budget_down": "Lower the budget by 20%",
        "leave": "Leave for now",
        "resume": "Switch back on",
        "keep_off": "Keep it off",
        "pause_ad": "Pause this advert",
        "add_creative": "Add a creative",
    },
}

TEXTS: Final[dict[str, dict[str, str]]] = {
    "uz": {
        "title.price.warn": "Narx {times} baravar qimmatlashdi",
        "title.price.stop": "To'xtatdim: narx {times} baravar qimmat",
        "title.fruitless.warn": "Pul sarflanyapti, natija yo'q",
        "title.fruitless.stop": "To'xtatdim: natija yo'q",
        "title.site_down.warn": "Reklama ochadigan sayt ishlamayapti",
        "title.site_down.stop": "To'xtatdim: sayt ochilmayapti",
        "title.weak_ad.warn": "Bitta reklama natija bermayapti",
        "title.ctr.warn": "Reklamaga kam bosishyapti",
        "title.cpm.warn": "Ko'rsatish narxi oshdi",
        "title.frequency.warn": "Reklama bir xil odamlarga ko'p ko'rsatilyapti",
        "price": "Bugun bitta {word}: {cost} ({results} ta). Odatda: {usual}.",
        "fruitless": "Bugun {spend} sarflandi, {word}: 0. Odatda bitta {word}: {usual}.",
        "site_down": "Reklamadagi havola ochilmayapti, odamlar bo'sh sahifaga tushyapti.",
        "weak_ad": "Bu reklama bugun {spend} sarfladi, {word}: 0. Guruhdagi boshqa reklama natija beryapti.",
        "ctr": "Bosish ulushi (CTR) {now}%, odatda {usual}%.",
        "cpm": "1000 ta ko'rsatish (CPM) {now}, odatda {usual}.",
        "frequency": "Oxirgi 7 kunda bir odam reklamani o'rtacha {now} marta ko'rdi.",
        "cause.cpm": "ko'rsatish qimmatlashgan (CPM {now}, odatda {usual})",
        "cause.ctr": "kam bosishyapti (CTR {now}%, odatda {usual}%)",
        "cause.conversion": "bosganlar natijaga aylanmayapti",
        "causes": "Sabab: {list}.",
        "no_cause": "Aniq sabab topilmadi: ko'rsatish narxi va bosish ulushi odatdagidek.",
        "stopped": "Pul behuda ketmasligi uchun guruhni to'xtatdim. Qayta yoqsangiz, hisob shu paytdan boshlanadi.",
        "next_stop": "Narx 5 baravarga yetsa, guruhni o'zim to'xtataman.",
        "advice": "Tavsiya: {button}.",
        "and": " va ",
    },
    "ru": {
        "title.price.warn": "Цена выросла в {times}",
        "title.price.stop": "Остановил: цена выше обычной в {times}",
        "title.fruitless.warn": "Деньги тратятся, результата нет",
        "title.fruitless.stop": "Остановил: нет результата",
        "title.site_down.warn": "Сайт из рекламы не открывается",
        "title.site_down.stop": "Остановил: сайт не открывается",
        "title.weak_ad.warn": "Одно объявление не даёт результата",
        "title.ctr.warn": "По рекламе мало кликают",
        "title.cpm.warn": "Показы подорожали",
        "title.frequency.warn": "Рекламу слишком часто видят одни и те же люди",
        "price": "Сегодня один {word}: {cost} (всего: {results}). Обычно: {usual}.",
        "fruitless": "Сегодня потрачено {spend}, {word}: 0. Обычно один {word}: {usual}.",
        "site_down": "Ссылка в рекламе не открывается, люди попадают на пустую страницу.",
        "weak_ad": "Это объявление сегодня потратило {spend}, {word}: 0. Другое объявление группы даёт результат.",
        "ctr": "Кликабельность (CTR) {now}%, обычно {usual}%.",
        "cpm": "1000 показов (CPM) {now}, обычно {usual}.",
        "frequency": "За 7 дней один человек видел рекламу в среднем {now} раза.",
        "cause.cpm": "показы подорожали (CPM {now}, обычно {usual})",
        "cause.ctr": "мало кликают (CTR {now}%, обычно {usual}%)",
        "cause.conversion": "клики не превращаются в результат",
        "causes": "Причина: {list}.",
        "no_cause": "Точная причина не найдена: цена показов и кликабельность как обычно.",
        "stopped": "Я остановил группу, чтобы деньги не уходили впустую. Если включите снова, счёт начнётся с этого момента.",
        "next_stop": "Если цена дойдёт до 5 раз, я сам остановлю группу.",
        "advice": "Совет: {button}.",
        "and": " и ",
    },
    "en": {
        "title.price.warn": "The price is {times} the usual",
        "title.price.stop": "Paused: the price is {times} the usual",
        "title.fruitless.warn": "Money is going out with nothing back",
        "title.fruitless.stop": "Paused: nothing back",
        "title.site_down.warn": "The advert's website does not open",
        "title.site_down.stop": "Paused: the website does not open",
        "title.weak_ad.warn": "One advert brings nothing",
        "title.ctr.warn": "Few people click the advert",
        "title.cpm.warn": "Showings got dearer",
        "title.frequency.warn": "The same people see the advert too often",
        "price": "Today one {word} costs {cost} ({results} so far). Usually: {usual}.",
        "fruitless": "Today {spend} was spent, {word}: 0. Usually one {word} costs {usual}.",
        "site_down": "The advert's link does not open: people land on an empty page.",
        "weak_ad": "This advert spent {spend} today, {word}: 0. Another advert of the group brings results.",
        "ctr": "Click rate (CTR) {now}%, usually {usual}%.",
        "cpm": "1,000 showings (CPM) cost {now}, usually {usual}.",
        "frequency": "Over 7 days one person saw the advert {now} times on average.",
        "cause.cpm": "showings got dearer (CPM {now}, usually {usual})",
        "cause.ctr": "few people click (CTR {now}%, usually {usual}%)",
        "cause.conversion": "clicks do not turn into results",
        "causes": "Cause: {list}.",
        "no_cause": "No clear cause: the showings' price and the click rate are as usual.",
        "stopped": "I paused the group so the money is not wasted. Switched back on, it is counted from that moment.",
        "next_stop": "At 5 times the usual price I will pause the group myself.",
        "advice": "Advice: {button}.",
        "and": " and ",
    },
}

# Which buttons a finding carries, in the order they are drawn.
_STOPPED: Final = ("resume", "keep_off")
_BUTTONS_FOR: Final[dict[str, tuple[str, ...]]] = {
    "price": ("pause", "budget_down", "leave"),
    "fruitless": ("pause", "leave"),
    "site_down": ("pause", "leave"),
    "weak_ad": ("pause_ad", "leave"),
    "ctr": ("add_creative", "leave"),
    "frequency": ("add_creative", "leave"),
    "cpm": ("leave", "pause"),
}


def _language() -> str:
    language = get_language()
    return language if language in TEXTS else DEFAULT


def _text(key: str, **values: Any) -> str:
    return TEXTS[_language()][key].format(**values)


def button_label(answer: str) -> str:
    return BUTTONS[_language()][answer]


def buttons_of(row: GuardAlert) -> tuple[str, ...]:
    """The answers a finding offers. A budget is lowered only where the
    group has one of its own; a stop offers the way back and nothing else."""
    if row.action == "stop":
        return _STOPPED
    found = _BUTTONS_FOR.get(row.kind, ("leave",))
    if not (row.figures or {}).get("own_budget"):
        found = tuple(answer for answer in found if answer != "budget_down")
    return found


def advised_of(row: GuardAlert) -> str:
    """The advised answer, or the first one where the advice is not offered."""
    offered = buttons_of(row)
    return row.advice if row.advice in offered else offered[0]


def word_of(row: GuardAlert) -> str:
    words = WORDS[_language()]
    return words.get(row.result_kind, words["lead"])


def times_of(times: int) -> str:
    """``320`` → "3,2 baravar"'s number, with the language's own tail."""
    whole, tenth = divmod(max(times, 0) // 10, 10)
    language = _language()
    number = f"{whole}" if not tenth else f"{whole},{tenth}"
    if language == "ru":
        # «в 5 раз», «в 3 раза», «в 3,2 раза».
        many = not tenth and (
            whole % 10 not in (2, 3, 4) or whole % 100 in (12, 13, 14)
        )
        return f"{number} {'раз' if many else 'раза'}"
    if language == "en":
        return f"{number.replace(',', '.')}×"
    return number


def guard_title(row: GuardAlert) -> str:
    return _text(f"title.{row.kind}.{row.action}", times=times_of(row.times))


def guard_body(row: GuardAlert) -> str:
    """The figures, the cause, and what was done or is coming."""
    lines = [_figures_line(row)]
    if row.kind in ("price", "fruitless"):
        lines.append(_causes_line(row))
    if row.action == "stop":
        lines.append(_text("stopped"))
    elif row.kind == "price" and (row.figures or {}).get("ours"):
        lines.append(_text("next_stop"))
    return "\n".join(line for line in lines if line)


def guard_advice(row: GuardAlert) -> str:
    """The advised answer, as a sentence: the cabinet prints it under the
    line, the phone as the message's last one."""
    return _text("advice", button=button_label(advised_of(row)))


def _money(row: GuardAlert, amount: Any) -> str:
    return format_minor(amount_minor=int(amount or 0), currency=row.currency)


def _percent(basis_points: Any) -> str:
    value = int(basis_points or 0)
    return f"{value // 100},{value % 100:02d}"


def _figures_line(row: GuardAlert) -> str:
    figures = row.figures or {}
    spend, results = (
        int(figures.get("spend_minor") or 0),
        int(figures.get("results") or 0),
    )
    usual = _money(row, figures.get("usual_cost_minor"))
    word = word_of(row)
    if row.kind == "price":
        cost = _money(row, formulas.cost_per_result(spend, results) or spend)
        return _text("price", word=word, cost=cost, results=results, usual=usual)
    if row.kind == "fruitless":
        return _text("fruitless", spend=_money(row, spend), word=word, usual=usual)
    if row.kind == "weak_ad":
        return _text("weak_ad", spend=_money(row, spend), word=word)
    if row.kind == "site_down":
        return _text("site_down")
    if row.kind == "frequency":
        return _text("frequency", now=_percent(figures.get("frequency")))
    now_ctr, now_cpm = _rates(figures)
    if row.kind == "ctr":
        return _text(
            "ctr",
            now=_percent(now_ctr),
            usual=_percent(figures.get("usual_link_ctr_bp")),
        )
    return _text(
        "cpm",
        now=_money(row, now_cpm),
        usual=_money(row, figures.get("usual_cpm_minor")),
    )


def _rates(figures: dict[str, Any]) -> tuple[int, int]:
    """Today's click rate in basis points and the price of a thousand showings."""
    shown = int(figures.get("impressions") or 0)
    clicked = int(figures.get("link_clicks") or 0)
    spend = int(figures.get("group_spend_minor") or figures.get("spend_minor") or 0)
    rate = basis_points_or_none(formulas.ctr(clicked, shown))
    return rate or 0, int(formulas.cpm(spend, shown) or 0)


def _causes_line(row: GuardAlert) -> str:
    figures = row.figures or {}
    now_ctr, now_cpm = _rates(figures)
    said: list[str] = []
    for cause in figures.get("causes") or []:
        if cause == "cpm":
            said.append(
                _text(
                    "cause.cpm",
                    now=_money(row, now_cpm),
                    usual=_money(row, figures.get("usual_cpm_minor")),
                )
            )
        elif cause == "ctr":
            said.append(
                _text(
                    "cause.ctr",
                    now=_percent(now_ctr),
                    usual=_percent(figures.get("usual_link_ctr_bp")),
                )
            )
        elif cause == "conversion":
            said.append(_text("cause.conversion"))
    if not said:
        # Without a usual rate to hold against, nothing is claimed either way.
        known = figures.get("usual_link_ctr_bp") and figures.get("usual_cpm_minor")
        return _text("no_cause") if known else ""
    return _text("causes", list=_text("and").join(said))


__all__ = [
    "BUTTONS",
    "TEXTS",
    "WORDS",
    "advised_of",
    "button_label",
    "buttons_of",
    "guard_advice",
    "guard_body",
    "guard_title",
    "times_of",
    "word_of",
]
