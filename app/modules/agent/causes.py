from collections.abc import Callable, Mapping
from typing import Any, Final

from app.common.dates import number_format
from app.common.money import format_minor
from app.modules.agent.constants import DiagnosisCause
from app.modules.agent.figures import bp_percent, decimal_of, whole
from app.modules.metrics.constants import Ranking
from core.agent.diagnosis import CAUSE_OF

_BOTTOM: Final = ("below_average_10", "below_average_20", "below_average_35")
_NAME_CHARS: Final = 40
Line = Callable[[Mapping[str, Any], str], str]


def _short(name: str) -> str:
    return name if len(name) <= _NAME_CHARS else f"{name[: _NAME_CHARS - 1].rstrip()}…"


def cause_label(cause: str) -> Any:
    if cause not in DiagnosisCause.values or cause == DiagnosisCause.NO_PROBLEM:
        return ""
    return DiagnosisCause(cause).label


def cause_line(diagnosis: Mapping[str, Any], *, currency: str) -> str:
    cause = str(diagnosis.get("cause", ""))
    if cause not in DiagnosisCause.values or cause == DiagnosisCause.NO_PROBLEM:
        return ""
    if cause == DiagnosisCause.UNCLEAR:
        return (
            "Natija odatdagidan yomon, lekin raqamlar aniq bir sababni ko'rsatmayapti."
        )
    evidence = diagnosis.get("evidence") or {}
    for signal in diagnosis.get("signals") or ():
        if CAUSE_OF.get(signal) == cause and signal in _LINES:
            return _LINES[signal](evidence, currency)
    return ""


def _provider_issue(evidence: Mapping[str, Any], currency: str) -> str:
    return "Reklama ko'rsatilmayapti: platforma guruhda xatolik topgan."


def _site_down(evidence: Mapping[str, Any], currency: str) -> str:
    urls = evidence.get("down_urls") or []
    if not urls:
        return ""
    return "Reklama olib boradigan sahifa ochilmayapti: %(url)s" % {"url": urls[0]}


def _learning(evidence: Mapping[str, Any], currency: str) -> str:
    return "Guruh hali o'rganish bosqichida - natija haqida gapirishga erta."


def _few_days(evidence: Mapping[str, Any], currency: str) -> str:
    days = _int(evidence, "days") or 0
    return "Guruh atigi %(days)d kun ishladi - natija haqida gapirishga erta." % {
        "days": days
    }


def _few_impressions(evidence: Mapping[str, Any], currency: str) -> str:
    shown = _int(evidence, "impressions") or 0
    return "Reklama hali %(count)s marta ko'rsatildi - baho berishga kam." % {
        "count": number_format(shown, force_grouping=True)
    }


def _worn_out(evidence: Mapping[str, Any], currency: str) -> str:
    before, after = (_int(evidence, "early_ctr_bp"), _int(evidence, "late_ctr_bp"))
    seen = _int(evidence, "late_frequency")
    if before is None or after is None or seen is None:
        return ""
    return (
        "Bir odam kuniga %(times)s marta ko'ryapti, bosish ulushi %(before)s dan %(after)s ga tushdi."
        % {
            "times": decimal_of(seen, 100),
            "before": bp_percent(before),
            "after": bp_percent(after),
        }
    )


def _low_ranking(evidence: Mapping[str, Any], currency: str) -> str:
    for verdict in evidence.get("rankings") or []:
        for value in (verdict.get("engagement"), verdict.get("quality")):
            if value not in _BOTTOM:
                continue
            name = str(verdict.get("name") or "").strip()
            if name:
                return (
                    "Platforma «%(ad)s» reklamasini o'xshash reklamalar orasida past baholagan: %(rank)s."
                    % {"ad": _short(name), "rank": Ranking(value).label}
                )
            return (
                "Platforma bu reklamani o'xshash reklamalar orasida past baholagan: %(rank)s."
                % {"rank": Ranking(value).label}
            )
    return ""


def _low_ctr(evidence: Mapping[str, Any], currency: str) -> str:
    own, usual = (_int(evidence, "link_ctr_bp"), _int(evidence, "account_link_ctr_bp"))
    if own is None or usual is None:
        return ""
    return (
        "1000 ko'rishdan %(own)s tasi bosilyapti, shu maqsaddagi boshqa reklamalaringizda o'rtacha %(usual)s tasi."
        % {"own": decimal_of(own, 10), "usual": decimal_of(usual, 10)}
    )


def _weak_hook(evidence: Mapping[str, Any], currency: str) -> str:
    own, usual = (_int(evidence, "hook_bp"), _int(evidence, "account_hook_bp"))
    if own is None:
        return ""
    if usual is None:
        return (
            "Videoni 3 soniyadan ko'proq ko'rganlar %(own)s - me'yor 20%% dan yuqori."
            % {"own": bp_percent(own)}
        )
    return "Videoni 3 soniyadan ko'proq ko'rganlar %(own)s, hisobingizda %(usual)s." % {
        "own": bp_percent(own),
        "usual": bp_percent(usual),
    }


def _fatigued(evidence: Mapping[str, Any], currency: str) -> str:
    then, now = (_int(evidence, "launch_ctr_bp"), _int(evidence, "recent_ctr_bp"))
    if then is None or now is None:
        return ""
    return (
        "Reklama yangi paytida bosish ulushi %(then)s edi, oxirgi 3 kunda %(now)s."
        % {"then": bp_percent(then), "now": bp_percent(now)}
    )


def _weak_hold(evidence: Mapping[str, Any], currency: str) -> str:
    own, usual = (_int(evidence, "hold_bp"), _int(evidence, "account_hold_bp"))
    if own is None:
        return ""
    if usual is None:
        return (
            "3 soniyadan o'tganlarning %(own)s videoni oxirigacha ko'rdi - me'yor 10%% dan yuqori."
            % {"own": bp_percent(own)}
        )
    return (
        "3 soniyadan o'tganlarning %(own)s videoni oxirigacha ko'rdi, hisobingizda %(usual)s."
        % {"own": bp_percent(own), "usual": bp_percent(usual)}
    )


def _junk_numbers(evidence: Mapping[str, Any], currency: str) -> str:
    junk, leads = (_int(evidence, "junk_leads"), _int(evidence, "leads"))
    if not junk or not leads:
        return ""
    return (
        "%(total)s ta murojaatdan %(junk)s tasida raqam noto'g'ri, boshqa davlatniki yoki takror (%(share)s%%)."
        % {"total": leads, "junk": junk, "share": round(junk * 100 / leads)}
    )


def _underspending(evidence: Mapping[str, Any], currency: str) -> str:
    share = _int(evidence, "spend_share")
    if share is None:
        return ""
    return "Reklama kunlik byudjetining faqat %(share)s%% ini sarfladi." % {
        "share": share
    }


def _learning_stuck(evidence: Mapping[str, Any], currency: str) -> str:
    results = _int(evidence, "results")
    if results is None:
        return ""
    return (
        "Bir haftada %(count)s ta natija - Meta o'rganishni tugatishi uchun taxminan 50 ta kerak."
        % {"count": results}
    )


def _high_cpm(evidence: Mapping[str, Any], currency: str) -> str:
    own, usual = (_int(evidence, "cpm_minor"), _int(evidence, "account_cpm_minor"))
    if own is None or usual is None:
        return ""
    return "1000 marta ko'rsatish %(own)s turadi, hisobingizda o'rtacha %(usual)s." % {
        "own": format_minor(amount_minor=own, currency=currency),
        "usual": format_minor(amount_minor=usual, currency=currency),
    }


def _quality_below_engagement(evidence: Mapping[str, Any], currency: str) -> str:
    return "Odamlar reklamani bosyapti, lekin platforma uning sifatini past baholagan: reklamadagi va'da haqiqiy taklifga mos kelmasligi mumkin."


def _low_click_to_lead(evidence: Mapping[str, Any], currency: str) -> str:
    clicks = _int(evidence, "link_clicks") or 0
    leads = _int(evidence, "leads") or 0
    line = "%(clicks)s bosishdan %(leads)s ta murojaat keldi." % {
        "clicks": number_format(clicks, force_grouping=True),
        "leads": leads,
    }
    usual = _int(evidence, "account_click_to_lead_bp")
    if usual is None:
        return line
    return (
        line
        + " "
        + "Hisobingizda har 100 bosishdan %(usual)s ta."
        % {"usual": decimal_of(usual, 100)}
    )


def _low_arrival(evidence: Mapping[str, Any], currency: str) -> str:
    clicks = _int(evidence, "link_clicks") or 0
    arrived = _int(evidence, "landing_page_views") or 0
    if clicks <= 0:
        return ""
    return "Bosganlarning faqat %(share)s saytga yetib keldi." % {
        "share": bp_percent(round(arrived * 10000 / clicks))
    }


def _conversion_ranking_low(evidence: Mapping[str, Any], currency: str) -> str:
    return "Odamlar qiziqyapti, lekin platforma natija bahosini past qo'ygan: bosgandan keyingi qadam to'sayotgan bo'lishi mumkin."


def _long_form(evidence: Mapping[str, Any], currency: str) -> str:
    count = _int(evidence, "form_questions") or 0
    return (
        "Formada %(count)d ta savol bor - har ortiqcha savol murojaatni kamaytiradi."
        % {"count": count}
    )


def _learning_limited(evidence: Mapping[str, Any], currency: str) -> str:
    return "Meta guruhni «o'rganish cheklangan» deb belgiladi: haftasiga kerakli natija yig'ilmayapti, shuning uchun narx barqaror emas."


_LINES: Final[dict[str, Line]] = {
    "provider_issue": _provider_issue,
    "site_down": _site_down,
    "learning_stuck": _learning_stuck,
    "learning": _learning,
    "few_days": _few_days,
    "few_impressions": _few_impressions,
    "underspending": _underspending,
    "worn_out": _worn_out,
    "fatigued": _fatigued,
    "low_ranking": _low_ranking,
    "low_ctr": _low_ctr,
    "weak_hook": _weak_hook,
    "weak_hold": _weak_hold,
    "high_cpm": _high_cpm,
    "quality_below_engagement": _quality_below_engagement,
    "low_click_to_lead": _low_click_to_lead,
    "low_arrival": _low_arrival,
    "conversion_ranking_low": _conversion_ranking_low,
    "junk_numbers": _junk_numbers,
    "long_form": _long_form,
    "learning_limited": _learning_limited,
}


def _int(evidence: Mapping[str, Any], key: str) -> int | None:
    return whole(evidence.get(key))


__all__ = ["cause_label", "cause_line"]
