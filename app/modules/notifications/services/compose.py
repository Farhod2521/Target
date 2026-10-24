from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from telegramkit import Button

from app.common.config import settings
from app.common.routes import reverse
from app.modules.miniapp.services import door_url
from app.modules.referrals.constants import FeedbackStatus, PayoutStatus
from core.chat.report import KindFigures
from core.inbox import InboxItem

if TYPE_CHECKING:
    from app.modules.agent.selectors import Card
FEEDBACK_MAX_CHARS: int = 400
SUPPORT_EXCERPT_CHARS: int = 200
EN_DASH: str = "–"


@dataclass(frozen=True, slots=True)
class Message:
    text: str
    suggestion_id: str = ""


def suggestion_message(*, card: Card) -> Message:
    lines = [_bold(str(card.rule_label)), escaped(card.target_name), ""]
    if card.result_line:
        lines.append(f"{escaped('Natija')}: {escaped(card.result_line)}")
    if card.cause_label:
        lines.append(f"{escaped('Sabab')}: {_bold(str(card.cause_label))}")
        if card.cause_line:
            lines.append(escaped(card.cause_line))
    lines.append(f"{escaped('Tavsiya etiladi')}: {_bold(str(card.kind_label))}")
    if card.note:
        lines.append(escaped(str(card.note)))
    if card.expectation:
        expected = " ".join(
            part for part in (str(card.expectation), card.expectation_figure) if part
        )
        lines.append(f"{escaped('Nima kutamiz')}: {escaped(expected)}")
    return Message(text="\n".join(lines), suggestion_id=str(card.pk))


def decided_message(*, card: Card, outcome: str) -> Message:
    lines = [
        _bold(str(card.rule_label)),
        escaped(card.target_name),
        "",
        f"{escaped('Javobingiz')}: {_bold(outcome)}",
    ]
    result = str(card.outcome_label) if card.outcome else str(card.review_note)
    if result:
        lines.append(f"{escaped('Natija')}: {escaped(result)}")
    return Message(text="\n".join(lines))


def outcome_message(*, card: Card) -> Message:
    lines = [
        _bold(str(card.rule_label)),
        escaped(card.target_name),
        "",
        f"{escaped('Nima qilindi')}: {escaped(str(card.kind_label))}",
        f"{escaped('Natija')}: {_bold(str(card.outcome_label))}",
    ]
    found = card.comparison
    if found is not None:
        lines.append(escaped(f"{found.label}: {found.before} → {found.after}"))
        if found.period:
            lines.append(escaped(found.period))
    return Message(text="\n".join(lines))


def _kind_line(row: KindFigures) -> str:
    return f"{escaped(str(row.label))}: {_bold(str(row.results))} · {escaped(str(row.cost_label))}: {_bold(row.cost)}"


def page_line(page: str) -> list[str]:
    if not page:
        return []
    return [f"{escaped('Sahifa')}: {_bold(escaped(page))}", ""]


def spend_guard_message(*, item: InboxItem, page: str = "") -> Message:
    lines = [*page_line(page), _bold(item.title)]
    if item.body:
        lines += ["", escaped(item.body)]
    lines += ["", _link(path=reverse("actions:home"), label="Kabinetda ochish")]
    return Message(text="\n".join(lines))


def paused_message() -> Message:
    return Message(
        text="\n".join(
            [
                _bold("To'xtatish so'raldi"),
                "",
                escaped(
                    "Guruh bir necha daqiqada to'xtaydi. Tarixi va qayta yoqish kabinetda."
                ),
            ]
        )
    )


def early_touch_message(*, hours: int) -> Message:
    return Message(
        text="\n".join(
            [
                _bold("Reklamaga hali tegmang"),
                "",
                escaped(
                    "Meta yangi reklamani o'rganyapti va unga 72 soat kerak. Hozir to'xtatsangiz, o'rganish noldan boshlanadi va pul qaytadan sarflanadi."
                ),
                "",
                escaped("Yana %(hours)d soat kuting." % {"hours": hours}),
            ]
        )
    )


def waiting_message() -> Message:
    return Message(
        text="\n".join(
            [
                _bold("Reklama ishlashda davom etadi"),
                "",
                escaped("72 soat o'tgach natijani birga ko'rib chiqamiz."),
            ]
        )
    )


def rejection_message(
    *, ad_name: str, group_name: str, feedback: Any, campaign_pk: Any, page: str = ""
) -> Message:
    lines = [
        *page_line(page),
        _bold("Reklama rad etildi"),
        escaped(_ad_title(ad_name=ad_name, group_name=group_name)),
    ]
    sentence = feedback_sentence(feedback)
    if sentence:
        lines += ["", escaped(sentence)]
    policies = _policy_names(feedback)
    if policies:
        lines.append(escaped("Meta qoidasi: %(names)s" % {"names": policies}))
    lines += [
        "",
        "Qaysi qoida buzilganini Meta'ning Business Support Home sahifasi aniq ko'rsatadi. U yerda qayta ko'rib chiqishni ham so'rash mumkin. Sabab rasm, video yoki matnda bo'lishi mumkin.",
        _link(
            path=reverse("ads:campaign", args=[campaign_pk]), label="Kabinetda ochish"
        ),
    ]
    return Message(text="\n".join(lines))


def expiry_message(*, plan_name: str, until: str, days: int, price: str) -> Message:
    plan_label = "Tarif"
    until_label = "Amal qilish muddati"
    price_label = "Yangilash narxi"
    lines = [
        _bold("Obuna muddati tugayapti"),
        "",
        f"{escaped(plan_label)}: {escaped(plan_name)}",
        f"{escaped(until_label)}: {escaped(until)}",
    ]
    if price:
        lines.append(f"{escaped(price_label)}: {escaped(price)}")
    lines += [
        "",
        escaped(
            "%(count)d kun qoldi. Obuna tugashi bilan platformada yaratilgan reklamalaringiz to'xtatiladi. 3 kun ichida to'lov qilinmasa, ular butunlay o'chiriladi. Lidlar va raqamlar joyida qoladi."
            % {"count": days}
        ),
        "",
        escaped("Muddat tugagunicha to'lovni amalga oshirishingizni so'raymiz."),
        "",
        _link(path=reverse("billing:plans"), label="Obunani yangilash"),
    ]
    return Message(text="\n".join(lines))


def trouble_message(*, item: InboxItem, page: str = "") -> Message:
    lines = [*page_line(page), _bold(item.title)]
    if item.subject is not None and item.subject.name:
        lines.append(escaped(item.subject.name))
    if item.body:
        lines += ["", escaped(item.body)]
    if item.action and item.href:
        lines += ["", _link(path=item.href, label=str(item.action))]
    return Message(text="\n".join(lines))


def connection_message() -> Message:
    return Message(
        text="\n".join(
            [
                _bold("Facebook ulanishi uzildi"),
                "",
                escaped(
                    "Yangi mijozlar ro'yxatga tushmayapti va sarf-xarajat raqamlari yangilanmayapti. Reklamangiz Facebook'da ishlashda davom etadi."
                ),
                "",
                _link(
                    path=reverse("integrations:connections"),
                    label="Kabinetda qayta ulash",
                ),
            ]
        )
    )


def action_required_message(*, person: str, manager_url: str) -> Message:
    who = (
        "Ads Manager'ga «%(name)s» profili bilan kiring." % {"name": person}
        if person
        else "Ads Manager'ga bizga ulangan Facebook profil bilan kiring."
    )
    lines = [
        _bold("Meta Facebook profilingizni tasdiqlashingizni so'rayapti"),
        "",
        escaped(
            "Yangi reklama yaratish uchun Meta profilingizni tasdiqlashingizni kutmoqda. Ishlayotgan reklamalaringiz to'xtamaydi."
        ),
        "",
        escaped(who),
        escaped(
            "Istalgan reklamada «Publish» tugmasini bosing — Meta shu yerda tasdiqlashni so'raydi. Keyin kabinetda «Tasdiqladim» ni bosing."
        ),
    ]
    if manager_url:
        label = escaped("Ads Manager'ni ochish")
        lines += ["", f'<a href="{escape(manager_url)}">{label}</a>']
    return Message(text="\n".join(lines))


def feedback_sentence(feedback: Any) -> str:
    if not isinstance(feedback, dict):
        return ""
    parts: list[str] = []
    for section in ("overall", "by_placement"):
        parts += _sentences(feedback.get(section))
    joined = " ".join(part for part in parts if part)
    if len(joined) <= FEEDBACK_MAX_CHARS:
        return joined
    return joined[: FEEDBACK_MAX_CHARS - 1].rstrip() + "…"


def _policy_names(feedback: Any) -> str:
    if not isinstance(feedback, dict):
        return ""
    names: list[str] = []
    for section in ("overall", "by_placement"):
        value = feedback.get(section)
        if not isinstance(value, dict):
            continue
        for key, inner in value.items():
            found = inner.keys() if isinstance(inner, dict) else [key]
            names += [str(name).strip() for name in found]
    return ", ".join(dict.fromkeys(name for name in names if name))


def _ad_title(*, ad_name: str, group_name: str) -> str:
    stem = group_name.rsplit(" · ", 1)[0]
    if not group_name or (stem and ad_name.startswith(stem)):
        return ad_name
    return f"{ad_name} · {group_name}"


def _sentences(section: Any) -> list[str]:
    if not isinstance(section, dict):
        return []
    found: list[str] = []
    for value in section.values():
        if isinstance(value, dict):
            found += [str(inner).strip() for inner in value.values()]
        else:
            found.append(str(value).strip())
    seen: set[str] = set()
    unique: list[str] = []
    for sentence in found:
        if sentence and sentence not in seen:
            seen.add(sentence)
            unique.append(sentence)
    return unique


def support_reply_message() -> Message:
    lines = [
        _bold("Yordam xizmati javob berdi"),
        "",
        _link(path=reverse("supportchat:chat"), label="Javobni ko'rish"),
    ]
    return Message(text="\n".join(lines))


def support_question_message(
    *, client: str, body: str, file_name: str, office_path: str
) -> Message:
    lines = [_bold("Yordamga yangi xabar"), escaped(client), ""]
    if body:
        lines.append(_quote(body))
    if file_name:
        lines.append(escaped("Fayl: %(name)s" % {"name": file_name}))
    lines += [
        "",
        _italic("Javob berish uchun shu xabarga reply qiling."),
        _link(path=office_path, label="Ofisda ochish"),
    ]
    return Message(text="\n".join(lines))


def support_answered_message(
    *, question: Message, name: str, at: str, answer: str
) -> Message:
    mark = _bold("✅ Javob berildi") + " — " + escaped(f"{name}, {at}")
    lines = [question.text, "", mark]
    if answer:
        lines.append(_quote(answer[:SUPPORT_EXCERPT_CHARS]))
    return Message(text="\n".join(lines))


def support_confirm_message(*, name: str, at: str) -> Message:
    text = (
        "Bu xabarga %(name)s %(at)s da javob bergan. Javobingiz baribir mijozga yuborilsinmi?"
        % {"name": name, "at": at}
    )
    return Message(text="⚠️ " + escaped(text))


def withdrawal_message(
    *, outcome: str, amount: str, card_last4: str, reason: str
) -> Message:
    card = f"•••• {card_last4}" if card_last4 else ""
    if outcome == PayoutStatus.PAID:
        lines = [
            _bold("Daromad: pul kartangizga o'tkazildi"),
            escaped(f"{amount} → {card}" if card else amount),
        ]
    else:
        lines = [
            _bold("Daromad: pul yechish so'rovi rad etildi"),
            escaped("%(amount)s balansingizga qaytdi." % {"amount": amount}),
            f"{escaped('Sabab')}: {escaped(reason)}",
        ]
    lines += ["", _link(path=reverse("referrals:wallet"), label="Daromadni ochish")]
    return Message(text="\n".join(lines))


def feedback_message(*, outcome: str, kind: str, amount: str, reason: str) -> Message:
    if outcome == FeedbackStatus.APPROVED:
        lines = [
            _bold("Fikringiz tasdiqlandi"),
            escaped(
                "%(kind)s: %(amount)s balansingizga tushdi."
                % {"kind": kind, "amount": amount}
            ),
        ]
    else:
        lines = [
            _bold("Fikringiz rad etildi"),
            f"{escaped('Sabab')}: {escaped(reason)}",
            escaped("Tuzatib, qayta yuborishingiz mumkin."),
        ]
    lines += [
        "",
        _link(path=f"{reverse('referrals:wallet')}?yol=fikr", label="Daromadni ochish"),
    ]
    return Message(text="\n".join(lines))


def miniapp_button(*, route: str, label: str, query: str = "") -> tuple[Button, ...]:
    if not settings.site_url.startswith("https://"):
        return ()
    destination = reverse(route) + (f"?{query}" if query else "")
    return (Button(text=label, web_app=door_url(destination=destination)),)


def ask_button(*, suggestion_id: str = "", item_key: str = "") -> tuple[Button, ...]:
    if suggestion_id:
        query = urlencode({"suggestion": suggestion_id})
    elif item_key:
        query = urlencode({"item": item_key})
    else:
        return ()
    return miniapp_button(route="chat:chat", label="Bu haqda so'rash", query=query)


def escaped(value: str) -> str:
    return escape(value, quote=False)


def _bold(text: str) -> str:
    return f"<b>{escaped(text)}</b>"


def _italic(text: str) -> str:
    return f"<i>{escaped(text)}</i>"


def _quote(text: str) -> str:
    return f"<blockquote>{escaped(text)}</blockquote>"


def _folded(title: str, rows: list[str]) -> str:
    body = "\n".join([escaped(title), *rows])
    return f"<blockquote expandable>{body}</blockquote>"


def _link(*, path: str, label: str) -> str:
    return f'<a href="{escape(settings.site_url + path)}">{escaped(label)}</a>'


__all__ = [
    "EN_DASH",
    "FEEDBACK_MAX_CHARS",
    "Message",
    "ask_button",
    "decided_message",
    "early_touch_message",
    "escaped",
    "expiry_message",
    "feedback_message",
    "feedback_sentence",
    "miniapp_button",
    "outcome_message",
    "page_line",
    "paused_message",
    "rejection_message",
    "spend_guard_message",
    "suggestion_message",
    "support_question_message",
    "support_reply_message",
    "trouble_message",
    "waiting_message",
    "withdrawal_message",
]
