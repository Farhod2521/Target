"""What the guard says after a button is pressed: uz, ru, en.

The line under a finding once it was answered - a change asked of the
provider, a second look at today's figures, the question whether a change is
still wanted, and what the provider did with it. Fixed sentences with the
figures put in, the same words in the cabinet and on the phone.
"""

from typing import Any, Final

from app.modules.agent.guard_copy import _language, _money, word_of
from app.modules.agent.models import GuardAlert
from core.metrics import formulas

TEXTS: Final[dict[str, dict[str, str]]] = {
    "uz": {
        "asked.pause": "⏳ To'xtatish so'rovi Meta'ga yuborildi. Natijani shu yerda yozaman.",
        "asked.pause_campaign": "⏳ Kampaniyani to'xtatish so'rovi Meta'ga yuborildi (unda bitta guruh). Natijani shu yerda yozaman.",
        "asked.pause_ad": "⏳ Reklamani to'xtatish so'rovi Meta'ga yuborildi. Natijani shu yerda yozaman.",
        "asked.budget_down": "⏳ Byudjetni kamaytirish so'rovi Meta'ga yuborildi: {old} → {new}. Natijani shu yerda yozaman.",
        "asked.resume": "⏳ Qayta yoqish so'rovi Meta'ga yuborildi. Natijani shu yerda yozaman.",
        "saved.leave": "✓ Qoldirildi. Narx yana oshsa, xabar beraman.",
        "saved.keep_off": "✓ Guruh to'xtatilgan holda qoladi.",
        "saved.cancel": "✓ Hech narsa o'zgartirilmadi. Yana yomonlashsa, xabar beraman.",
        "checking": "🔎 Bu raqamlar {minutes} daqiqa oldingi. Hozirgi holatni Meta'dan tekshiryapman…",
        "confirm": "✅ Hozir yaxshi ishlayapti: {now}\nBaribir {question}",
        "confirm.unread": "⚠️ Meta'dan hozirgi raqamlarni o'qib bo'lmadi. Oxirgi raqamlar {minutes} daqiqa oldingi.\nBaribir {question}",
        "question.pause": "to'xtataymi?",
        "question.pause_campaign": "kampaniyani to'xtataymi?",
        "question.pause_ad": "reklamani to'xtataymi?",
        "question.budget_down": "byudjetni {old} → {new} qilaymi?",
        "now.results": "bugun {spend} sarflandi, {results} ta {word}, bittasi {cost}.",
        "now.results_usual": "bugun {spend} sarflandi, {results} ta {word}, bittasi {cost} (odatda {usual}).",
        "now.none": "bugun {spend} sarflandi, {word} hali yo'q.",
        "now.site": "sahifa hozir ochilyapti.",
        "gone": "ℹ️ Guruh hozir ishlamayapti, hech narsa o'zgartirilmadi.",
        "done.pause": "✅ Bajarildi: guruh to'xtatildi.",
        "done.pause_campaign": "✅ Bajarildi: kampaniya to'xtatildi.",
        "done.pause_ad": "✅ Bajarildi: reklama to'xtatildi.",
        "done.budget_down": "✅ Bajarildi: kunlik byudjet {new}.",
        "done.resume": "✅ Bajarildi: qayta yoqildi.",
        "failed": "❌ Meta bajarmadi: {why}",
        "title.stop_failed": "To'xtata olmadim",
        "stop_failed": "Guruhni o'zim to'xtatmoqchi edim, Meta bajarmadi: {why}",
        "button.confirm.pause": "Ha, to'xtat",
        "button.confirm.pause_ad": "Ha, to'xtat",
        "button.confirm.budget_down": "Ha, kamaytir",
        "button.cancel": "Yo'q, qoldir",
        "said.checking": "Hozirgi raqamlarni tekshiryapman.",
        "said.busy": "Tekshiruv ketyapti, biroz kuting.",
        "said.cancel": "Hech narsa o'zgartirilmadi.",
    },
    "ru": {
        "asked.pause": "⏳ Запрос на остановку отправлен в Meta. Результат напишу здесь.",
        "asked.pause_campaign": "⏳ Запрос на остановку кампании отправлен в Meta (в ней одна группа). Результат напишу здесь.",
        "asked.pause_ad": "⏳ Запрос на остановку объявления отправлен в Meta. Результат напишу здесь.",
        "asked.budget_down": "⏳ Запрос на снижение бюджета отправлен в Meta: {old} → {new}. Результат напишу здесь.",
        "asked.resume": "⏳ Запрос на включение отправлен в Meta. Результат напишу здесь.",
        "saved.leave": "✓ Оставлено. Если цена вырастет ещё, я сообщу.",
        "saved.keep_off": "✓ Группа останется выключенной.",
        "saved.cancel": "✓ Ничего не изменено. Если станет хуже, я сообщу.",
        "checking": "🔎 Этим цифрам {minutes} мин. Проверяю текущее состояние в Meta…",
        "confirm": "✅ Сейчас работает хорошо: {now}\nВсё равно {question}",
        "confirm.unread": "⚠️ Не удалось прочитать текущие цифры из Meta. Последним цифрам {minutes} мин.\nВсё равно {question}",
        "question.pause": "остановить?",
        "question.pause_campaign": "остановить кампанию?",
        "question.pause_ad": "остановить объявление?",
        "question.budget_down": "сделать бюджет {old} → {new}?",
        "now.results": "сегодня потрачено {spend}, результатов ({word}): {results}, один стоит {cost}.",
        "now.results_usual": "сегодня потрачено {spend}, результатов ({word}): {results}, один стоит {cost} (обычно {usual}).",
        "now.none": "сегодня потрачено {spend}, результатов ({word}) пока нет.",
        "now.site": "страница сейчас открывается.",
        "gone": "ℹ️ Группа сейчас не работает, ничего не изменено.",
        "done.pause": "✅ Готово: группа остановлена.",
        "done.pause_campaign": "✅ Готово: кампания остановлена.",
        "done.pause_ad": "✅ Готово: объявление остановлено.",
        "done.budget_down": "✅ Готово: дневной бюджет {new}.",
        "done.resume": "✅ Готово: снова включено.",
        "failed": "❌ Meta не выполнила: {why}",
        "title.stop_failed": "Не удалось остановить",
        "stop_failed": "Я хотел остановить группу сам, Meta не выполнила: {why}",
        "button.confirm.pause": "Да, остановить",
        "button.confirm.pause_ad": "Да, остановить",
        "button.confirm.budget_down": "Да, снизить",
        "button.cancel": "Нет, оставить",
        "said.checking": "Проверяю текущие цифры.",
        "said.busy": "Проверка идёт, подождите немного.",
        "said.cancel": "Ничего не изменено.",
    },
    "en": {
        "asked.pause": "⏳ The pause was sent to Meta. I will write the result here.",
        "asked.pause_campaign": "⏳ The campaign's pause was sent to Meta (it has one ad set). I will write the result here.",
        "asked.pause_ad": "⏳ The advert's pause was sent to Meta. I will write the result here.",
        "asked.budget_down": "⏳ The lower budget was sent to Meta: {old} → {new}. I will write the result here.",
        "asked.resume": "⏳ The switch-on was sent to Meta. I will write the result here.",
        "saved.leave": "✓ Left as it is. If the price goes up further, I will tell you.",
        "saved.keep_off": "✓ The ad set stays off.",
        "saved.cancel": "✓ Nothing was changed. If it gets worse, I will tell you.",
        "checking": "🔎 These figures are {minutes} minutes old. Checking the present state at Meta…",
        "confirm": "✅ It works well now: {now}\nStill {question}",
        "confirm.unread": "⚠️ Today's figures could not be read from Meta. The last ones are {minutes} minutes old.\nStill {question}",
        "question.pause": "pause it?",
        "question.pause_campaign": "pause the campaign?",
        "question.pause_ad": "pause the advert?",
        "question.budget_down": "make the budget {old} → {new}?",
        "now.results": "{spend} spent today, {results} {word} so far, {cost} each.",
        "now.results_usual": "{spend} spent today, {results} {word} so far, {cost} each (usually {usual}).",
        "now.none": "{spend} spent today, no {word} yet.",
        "now.site": "the page opens now.",
        "gone": "ℹ️ The ad set is not running now; nothing was changed.",
        "done.pause": "✅ Done: the ad set is paused.",
        "done.pause_campaign": "✅ Done: the campaign is paused.",
        "done.pause_ad": "✅ Done: the advert is paused.",
        "done.budget_down": "✅ Done: the daily budget is {new}.",
        "done.resume": "✅ Done: switched back on.",
        "failed": "❌ Meta did not do it: {why}",
        "title.stop_failed": "Could not pause",
        "stop_failed": "I meant to pause the ad set myself; Meta did not do it: {why}",
        "button.confirm.pause": "Yes, pause",
        "button.confirm.pause_ad": "Yes, pause",
        "button.confirm.budget_down": "Yes, lower it",
        "button.cancel": "No, leave it",
        "said.checking": "Checking today's figures.",
        "said.busy": "The check is running, one moment.",
        "said.cancel": "Nothing was changed.",
    },
}


def follow_text(key: str, **values: Any) -> str:
    return TEXTS[_language()][key].format(**values)


def _sole(row: GuardAlert) -> bool:
    return bool((row.figures or {}).get("sole_group")) and row.level != "ad"


def _answer_key(row: GuardAlert, answer: str) -> str:
    """``pause`` on a campaign's one group is the campaign's pause."""
    return "pause_campaign" if answer == "pause" and _sole(row) else answer


def budgets(row: GuardAlert) -> tuple[str, str]:
    figures = row.figures or {}
    old = int(figures.get("budget_old_minor") or figures.get("day_budget_minor") or 0)
    new = int(figures.get("budget_new_minor") or 0)
    return _money(row, old), _money(row, new)


def asked_line(row: GuardAlert, answer: str) -> str:
    old, new = budgets(row)
    return follow_text(f"asked.{_answer_key(row, answer)}", old=old, new=new)


def done_line(row: GuardAlert, answer: str) -> str:
    _old, new = budgets(row)
    return follow_text(f"done.{_answer_key(row, answer)}", new=new)


def question_of(row: GuardAlert, answer: str) -> str:
    old, new = budgets(row)
    return follow_text(f"question.{_answer_key(row, answer)}", old=old, new=new)


def now_line(row: GuardAlert) -> str:
    """Today's figures as the second look read them."""
    now = row.now_figures or {}
    if row.kind == "site_down":
        return follow_text("now.site")
    spend = int(now.get("spend_minor") or 0)
    results = int(now.get("results") or 0)
    word = word_of(row)
    if results <= 0:
        return follow_text("now.none", spend=_money(row, spend), word=word)
    cost = _money(row, formulas.cost_per_result(spend, results) or spend)
    usual = now.get("usual_cost_minor")
    if usual:
        return follow_text(
            "now.results_usual",
            spend=_money(row, spend),
            results=results,
            word=word,
            cost=cost,
            usual=_money(row, usual),
        )
    return follow_text(
        "now.results", spend=_money(row, spend), results=results, word=word, cost=cost
    )


def confirm_line(row: GuardAlert, *, minutes: int) -> str:
    question = question_of(row, row.pending_answer)
    if (row.now_figures or {}).get("unread"):
        return follow_text("confirm.unread", minutes=minutes, question=question)
    return follow_text("confirm", now=now_line(row), question=question)


def confirm_label(answer: str) -> str:
    return follow_text(f"button.confirm.{answer}")


def follow_of(row: GuardAlert) -> tuple[str, tuple[str, ...] | None]:
    """The line under a finding after an answer, and the buttons it carries
    now: ``()`` none, ``None`` the finding's own."""
    from app.modules.agent.services.answer_guard import (
        CHANGING,
        CHECKING_STATE,
        CONFIRM_STATE,
    )
    from app.modules.agent.services.recheck_guard import minutes_old

    if row.pending_state == CHECKING_STATE:
        return follow_text("checking", minutes=minutes_old(row, at=row.pending_at)), ()
    if row.pending_state == CONFIRM_STATE:
        line = confirm_line(row, minutes=minutes_old(row, at=row.pending_at))
        return line, ("confirm", "cancel")
    if row.result == "gone":
        return row.result_text or follow_text("gone"), ()
    if row.answer in ("leave", "keep_off") and not row.answer_log_id:
        return follow_text(f"saved.{row.answer}"), ()
    if row.action == "stop" and not row.answer_log_id:
        # The guard's own stop: its body says what was done or refused.
        return "", None
    if row.result == "failed":
        return follow_text("failed", why=row.result_text), None
    if row.answer_log_id and row.answer in CHANGING:
        if row.result == "applied":
            return done_line(row, row.answer), ()
        return asked_line(row, row.answer), ()
    if row.answer in ("leave", "keep_off"):
        return follow_text(f"saved.{row.answer}"), ()
    return "", None


__all__ = [
    "TEXTS",
    "asked_line",
    "budgets",
    "confirm_label",
    "confirm_line",
    "done_line",
    "follow_of",
    "follow_text",
    "now_line",
    "question_of",
]
