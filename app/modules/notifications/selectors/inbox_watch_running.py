"""What the watch says about a group past its first week."""

from collections.abc import Callable

from adskit import MinorUnits

from app.common.money import format_minor
from app.modules.agent.selectors.watched import Watched
from app.modules.metrics.selectors.results import words_for
from core.agent.running_watch import RECENT_DAYS, Running, Tally
from core.agent.usual import TREND_DAYS
from core.metrics import cost_per


def running_body(row: Watched, facts: Running) -> str:
    """The line's body for a running group's step."""
    body: dict[str, Callable[[Watched, Running], str]] = {
        "stalled": _stalled,
        "dry": _dry,
        "dearer": _dearer,
        "cheaper": _cheaper,
    }
    return body[row.watch.stage](row, facts)


def _stalled(row: Watched, facts: Running) -> str:
    said = (
        "Oxirgi %(days)s kunda bu guruhga hech narsa sarflanmadi, oldin esa "
        "sarflanardi. Sabab ko'pincha shulardan biri: byudjet auksionda "
        "yutishga yetmayapti, akkauntdagi sarf limiti tugagan yoki Meta "
        "reklamani cheklagan."
    ) % {"days": facts.idle_days}
    if row.watch.advised == "budget_up":
        advice = (
            "Byudjetni %(pct)s%% oshirib ko'ring va kabinetda holatini tekshiring."
        ) % {"pct": row.watch.step_pct}
    else:
        advice = "Kabinetda kampaniya holatini tekshiring."
    return f"{said} {advice}"


def _dry(row: Watched, facts: Running) -> str:
    figures = {
        "days": facts.dry_days,
        "spend": _money(row, facts.dry_spend_minor),
        "label": words_for(row.kind).label,
    }
    said = "Oxirgi %(days)s kunda %(spend)s sarflandi, %(label)s: 0." % figures
    expected = facts.expected_cost_minor
    if expected:
        said += " " + (
            "Odatda bitta natija %(usual)s turadi - shu pulga taxminan "
            "%(could)s ta kelishi kerak edi."
        ) % {
            "usual": _money(row, expected),
            "could": facts.dry_spend_minor // expected,
        }
    if row.watch.advised == "pause":
        advice = (
            "Guruhni to'xtating va sababini ko'ring: odamlar reklamani "
            "bosmayotgan bo'lsa - rasm yoki matnni yangilang; bosib, lekin "
            "murojaat qoldirmayotgan bo'lsa - formani soddalashtiring."
        )
    else:
        advice = (
            "Yana bir necha kun kuzatamiz. Shunday davom etsa, to'xtatishni "
            "taklif qilamiz."
        )
    return f"{said} {advice}"


def _dearer(row: Watched, facts: Running) -> str:
    last, usual = facts.last, facts.usual_cost_minor or 0
    cost = _cost(last)
    tenths = (cost * 10) // usual if usual else 0
    said = (
        "%(cost_label)s oxirgi %(days)s kunda %(recent)s (%(count)s ta), "
        "odatda %(usual)s. Bu %(times)s barobar qimmat."
    ) % {
        "cost_label": words_for(row.kind).cost_label,
        "days": TREND_DAYS,
        "recent": _money(row, cost),
        "count": last.results,
        "usual": _money(row, usual),
        "times": f"{tenths // 10},{tenths % 10}",
    }
    advice = (
        "Byudjet kampaniyadagi boshqa guruhlar bilan umumiy, shuning uchun uni "
        "shu yerdan o'zgartirmaymiz. Guruhni to'xtatib, rasm yoki formani "
        "yangilang."
    )
    return f"{said} {advice}"


def _cheaper(row: Watched, facts: Running) -> str:
    advice = (
        "Byudjet to'liq sarflanyapti - uni %(pct)s%% oshirsangiz, shu narxda "
        "ko'proq natija olish mumkin. Oshirgandan keyin narx 3-4 kun "
        "o'zgarib turadi, shundan keyin yana qaraymiz."
    ) % {"pct": row.watch.step_pct}
    return f"{_compared(row, facts)} {advice}"


def _compared(row: Watched, facts: Running) -> str:
    return (
        "%(cost_label)s oxirgi %(recent_days)s kunda %(recent)s "
        "(%(recent_n)s ta), undan oldingi %(before_days)s kunda %(before)s "
        "edi (%(before_n)s ta)."
    ) % {
        "cost_label": words_for(row.kind).cost_label,
        "recent_days": RECENT_DAYS,
        "recent": _money(row, _cost(facts.recent)),
        "recent_n": facts.recent.results,
        "before_days": facts.before_days,
        "before": _money(row, _cost(facts.before)),
        "before_n": facts.before.results,
    }


def _cost(tally: Tally) -> int:
    return cost_per(MinorUnits(tally.spend_minor), tally.results) or 0


def _money(row: Watched, amount_minor: int) -> str:
    return format_minor(amount_minor=amount_minor, currency=row.currency)


__all__ = ["running_body"]
