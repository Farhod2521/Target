"""Last night's diagnosis of a group, as the words beside it in a conversation."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.recommendations import WEAK_CONFIDENCE
from app.modules.agent.causes import cause_label, cause_line
from app.modules.agent.figures import decimal_of
from app.modules.agent.models import AdSetDiagnosis
from app.modules.agent.selectors.policy import diagnoses
from app.modules.metrics.constants import BreakdownKind


@dataclass(frozen=True, slots=True)
class Reading:
    """The diagnosis's half of one group line. Every field may be empty."""

    cause: str = ""
    shown_cost: str = ""
    click_rate: str = ""
    frequency: str = ""
    costly_slice: str = ""


NOTHING = Reading()


def diagnoses_for(
    db: Session, *, owner: User, adset_ids: Iterable[str]
) -> dict[str, AdSetDiagnosis]:
    """``{ad set id: last night's row}`` for these groups. One query."""
    ids = list(adset_ids)
    if not ids:
        return {}
    return {
        row.adset_external_id: row
        for row in db.scalars(
            diagnoses(owner).where(AdSetDiagnosis.adset_external_id.in_(ids))
        )
    }


def reading_of(row: AdSetDiagnosis | None, *, currency: str) -> Reading:
    """What the diagnosis says about one group, or nothing if it has no row."""
    if row is None:
        return NOTHING
    evidence = row.evidence or {}

    def money(value: int) -> str:
        return format_minor(amount_minor=value, currency=currency)

    return Reading(
        cause=_cause(row, currency=currency),
        shown_cost=_beside(evidence, "cpm_minor", "account_cpm_minor", money),
        click_rate=_beside(
            evidence,
            "link_ctr_bp",
            "account_link_ctr_bp",
            lambda value: decimal_of(value, 10),
        ),
        frequency=_frequency(evidence),
        costly_slice=_slice(evidence.get("costly_slice"), money=money),
    )


def advice_of(recommendations: object) -> str:
    """The provider's first confident piece of advice about a group, its title."""
    if not isinstance(recommendations, list):
        return ""
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        if str(item.get("confidence") or "").strip().upper() in WEAK_CONFIDENCE:
            continue
        title = str(item.get("title") or item.get("message") or "").strip()
        if title:
            return title
    return ""


def _cause(row: AdSetDiagnosis, *, currency: str) -> str:
    label = cause_label(row.cause)
    if not label:
        return ""
    line = cause_line(
        {"cause": row.cause, "signals": row.signals, "evidence": row.evidence},
        currency=currency,
    )
    return f"{label} - {line}" if line else str(label)


def _beside(
    evidence: Mapping[str, Any],
    own_key: str,
    usual_key: str,
    shown: Callable[[int], str],
) -> str:
    """ "5 USD (account 3 USD)", or the group's own figure when the account has none."""
    own = _int(evidence, own_key)
    if own is None:
        return ""
    usual = _int(evidence, usual_key)
    if usual is None:
        return shown(own)
    return f"{shown(own)} (account {shown(usual)})"


def _frequency(evidence: Mapping[str, Any]) -> str:
    early, late = _int(evidence, "early_frequency"), _int(evidence, "late_frequency")
    if late is None:
        return ""
    if early is None:
        return decimal_of(late, 100)
    return f"{decimal_of(early, 100)} -> {decimal_of(late, 100)}"


def _slice(found: object, *, money: Callable[[int], str]) -> str:
    """The dear slice in one phrase: which cut, which part, what share, what price."""
    if not isinstance(found, dict):
        return ""
    share, cpm = _int(found, "spend_share_pct"), _int(found, "cpm_minor")
    if share is None or cpm is None:
        return ""
    kind = str(found.get("kind", ""))
    try:
        cut = str(BreakdownKind(kind).label)
    except ValueError:
        cut = kind
    return (
        f"{cut} {found.get('segment', '')}: {share}% of the money "
        f"at {money(cpm)} per 1000 shown"
    )


def _int(evidence: Mapping[str, Any], key: str) -> int | None:
    value = evidence.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


__all__ = ["NOTHING", "Reading", "advice_of", "diagnoses_for", "reading_of"]
