"""A refused change to a running advert, read for the answer that explains it."""

from typing import Final

from metaads.accounts import ACCOUNT_QUALITY_URL, billing_url, manager_url
from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.ads.constants import ManagedLevel
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from app.modules.chat.selectors.refusal import ready_answer
from core.chat.links import Link
from core.chat.refusal import CHANGE_PREFIX, ChangeFacts, change_refusal_key

CHANGES: Final[dict[str, str]] = {
    ActionType.PAUSE: "switching it off",
    ActionType.RESUME: "switching it on",
    ActionType.BUDGET_UP: "a daily budget change",
    ActionType.BUDGET_DOWN: "a daily budget change",
    ActionType.TARGETING_SWAP: "an audience change",
    ActionType.END_TIME_SET: "an end date",
    ActionType.SPEND_CAP_SET: "a campaign spending limit",
    ActionType.CREATIVE_SWAP: "a new version of the advert",
    ActionType.CREATE_ADSET: "a new ad set in the campaign",
    ActionType.CREATE_AD: "a new advert in the ad set",
    ActionType.DELETE_CAMPAIGN: "deleting it",
    ActionType.DELETE_ADSET: "deleting it",
    ActionType.DELETE_AD: "deleting it",
}
LEVELS: Final[dict[str, str]] = {
    ManagedLevel.CAMPAIGN: "a campaign",
    ManagedLevel.ADSET: "an ad group",
    ManagedLevel.AD: "an advert",
}
MEANINGS: Final[dict[str, str]] = {
    "ulanish": "the Meta connection here, where Meta is connected again",
    "tolov": "Meta's billing page for this ad account: cards, bills",
    "ads_manager": "Meta Ads Manager, opened on this ad account",
    "akkaunt_sifati": "Meta's account quality page: restrictions and appeals",
}


def change_key(log: ActionLog) -> str:
    named = str((log.result_payload or {}).get("key") or "")
    if named:
        return f"{CHANGE_PREFIX}:{named}"
    return change_refusal_key(
        provider=log.target_provider, error_message=log.error_message
    )


def change_links(account_external_id: str) -> dict[str, Link]:
    """Every address an answer about a refused change may point at."""
    return {
        "ulanish": Link("Ulanishlar", reverse("integrations:connections")),
        "tolov": Link("To'lov sahifasini ochish", billing_url(account_external_id)),
        "ads_manager": Link("Ads Manager'ni ochish", manager_url(account_external_id)),
        "akkaunt_sifati": Link("Akkaunt holati (Meta)", ACCOUNT_QUALITY_URL),
    }


def change_facts(log: ActionLog) -> ChangeFacts:
    said = log.result_payload or {}
    return ChangeFacts(
        change=CHANGES.get(log.action, log.action),
        level=LEVELS.get(log.target_level, log.target_level),
        provider_title=str(said.get("user_title") or ""),
        provider_message=str(said.get("user_message") or ""),
        developer_message=log.error_message,
        links=tuple(MEANINGS.items()),
    )


def change_explanation(db: Session, *, log: ActionLog, language: str) -> str:
    """The answer already written for this refusal, in this language, or empty."""
    found = ready_answer(db, key=change_key(log), language=language)
    return found.text if found is not None else ""


__all__ = [
    "CHANGES",
    "MEANINGS",
    "change_explanation",
    "change_facts",
    "change_key",
    "change_links",
]
