"""A change the owner asked the assistant for: prepared in the answer, carried out only on their press.

The model never changes anything. Its ``propose_change`` look-up runs the same
checks the campaigns screen runs (``actions.preview``) without opening a
change, and a change that would be refused is answered with the
refusal instead of a button. What is kept on the answer's row is what the
product read itself - the object, its name, the figure before and after - so the
button says exactly what will happen. Pressing it calls the campaigns screen's
own service, which checks everything again against the account as it is then.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.audit.constants import ActionStatus
from app.modules.audit.models import ActionLog
from app.modules.chat.models import ChatMessage
from core.agent.guardrails import ACTIVE, PAUSED
from core.chat.lookup_arguments import ChangeProposal

CHANGE_KIND: Final = "change"
KEY_PREFIX: Final = "P"

OPEN: Final = "open"
SENT: Final = "sent"
DISMISSED: Final = "dismissed"

WHAT: Final[dict[str, str]] = {
    "budget": "Kunlik budjetni o'zgartirish",
    "pause": "To'xtatish",
    "resume": "Qayta yoqish",
}
LEVEL_WORDS: Final[dict[str, str]] = {
    ManagedLevel.CAMPAIGN: "kampaniya",
    ManagedLevel.ADSET: "reklama guruhi",
    ManagedLevel.AD: "reklama",
}
STATE_WORDS: Final[dict[str, str]] = {ACTIVE: "Yoqilgan", PAUSED: "To'xtatilgan"}

WORKING: Final = "Bajarilmoqda."
APPLIED: Final = "Bajarildi."
FAILED_WORDS: Final = "Meta bu o'zgarishni qabul qilmadi."
GONE_WORDS: Final = "Bu taklif endi mavjud emas."


@dataclass(frozen=True, slots=True)
class Prepared:
    """What the look-up answers the model, and the button it leaves, if any."""

    text: str
    item: dict[str, Any] | None = None


def prepare_change(
    db: Session,
    *,
    owner: User,
    arguments: ChangeProposal,
    scope: PageScope,
    key: str,
) -> Prepared:
    """Check the change the way the campaigns screen would, and describe it, or say why not."""
    from app.modules.ads import actions
    from app.modules.ads.selectors.actions import account_of, managed_target

    level, external_id = arguments.level, arguments.object_id
    target = managed_target(db, owner=owner, level=level, external_id=external_id)
    if target is None:
        return Prepared(
            text=f"Nothing with id {external_id} at level {level}. Look it up first; never guess an id."
        )
    if not _inside(scope, level=level, target=target):
        return Prepared(
            text="This object is not on the page this conversation is about. Say so; do not offer a change."
        )
    account = account_of(target=target, level=level)
    name = str(getattr(target, "name", "") or external_id)
    try:
        if arguments.action == "budget":
            item = _budget(
                db, owner=owner, arguments=arguments, target=target, account=account
            )
        else:
            wanted = PAUSED if arguments.action == "pause" else ACTIVE
            item = {
                "before": STATE_WORDS.get(
                    _status_of(target), str(getattr(target, "delivery", ""))
                ),
                "after": STATE_WORDS[wanted],
            }
        actions.preview(
            db, user=owner, ask=_ask(arguments.action, level, external_id, item)
        )
    except _NotABudget as exc:
        return Prepared(text=str(exc))
    except DomainError as exc:
        return Prepared(
            text=f"It cannot be prepared - the product refuses it: {exc}. Tell the owner this, in their words."
        )
    item |= {
        "kind": CHANGE_KIND,
        "key": key,
        "action": arguments.action,
        "level": level,
        "external_id": external_id,
        "target": name,
        "target_kind": LEVEL_WORDS.get(level, level),
        "label": WHAT[arguments.action],
        "state": OPEN,
        "log_id": "",
    }
    return Prepared(
        text=(
            f'Prepared as {key}: {item["label"]} - {item["target_kind"]} "{name}", '
            f"{item['before']} -> {item['after']}. The owner now sees a confirm button "
            "under your answer; nothing has changed and nothing will until they press it. "
            f"End your answer with the line %%CHOICE%% {key}. Say what will change in one "
            "sentence and never say it is done."
        ),
        item=item,
    )


class _NotABudget(Exception):
    pass


def _budget(
    db: Session, *, owner: User, arguments: ChangeProposal, target: Any, account: Any
) -> dict[str, Any]:
    from app.common.money import provider_money

    if arguments.level == ManagedLevel.AD:
        raise _NotABudget(
            "An advert has no budget of its own; its ad group or campaign does."
        )
    if not arguments.daily_budget:
        raise _NotABudget(
            "A budget change needs the new daily amount. Ask the owner for it."
        )
    current = getattr(target, "daily_budget_minor", None)
    if not current:
        where = (
            "its ad groups"
            if arguments.level == ManagedLevel.CAMPAIGN
            else "its campaign"
        )
        raise _NotABudget(
            f"This {arguments.level} has no daily budget of its own - {where} carry it. "
            "Look up campaign_details and propose the change there."
        )
    currency = account.currency
    wanted = int(
        provider_money(provider=account.provider).to_minor(
            amount=arguments.daily_budget.replace(",", "."), currency=currency
        )
    )
    if wanted == current:
        raise _NotABudget("That is already its daily budget. Nothing to change.")
    return {
        "before": format_minor(amount_minor=current, currency=currency),
        "after": format_minor(amount_minor=wanted, currency=currency),
        "daily_budget_minor": wanted,
        "currency": currency,
    }


def _ask(action: str, level: str, external_id: str, item: dict[str, Any]) -> Any:
    """The change the button stands for, as the campaigns screen asks for it."""
    from app.modules.ads import actions

    if action == "budget":
        return actions.Budget(
            level=level,
            external_id=external_id,
            daily_budget_minor=int(item["daily_budget_minor"]),
        )
    if action == "pause":
        return actions.Pause(level=level, external_id=external_id)
    return actions.Resume(level=level, external_id=external_id)


def _status_of(target: Any) -> str:
    delivery = str(getattr(target, "delivery", ""))
    if delivery == "active":
        return ACTIVE
    if delivery in {"paused", "paused_above"}:
        return PAUSED
    return delivery


def _inside(scope: PageScope, *, level: str, target: Any) -> bool:
    if level == ManagedLevel.CAMPAIGN:
        return scope.allows_campaign(str(target.external_id))
    if level == ManagedLevel.ADSET:
        return scope.allows_adset(str(target.external_id))
    parent = getattr(target, "adset", None)
    return parent is not None and scope.allows_adset(str(parent.external_id))


@dataclass(frozen=True, slots=True)
class ChangeState:
    """Where one prepared change has got to, in the words the button shows."""

    state: str
    text: str


def _found(
    db: Session, *, owner: User, message_id: str, key: str
) -> tuple[ChatMessage | None, int]:
    try:
        pk = uuid.UUID(str(message_id))
    except ValueError:
        return None, -1
    row = db.scalar(
        select(ChatMessage).where(
            ChatMessage.owner_id == owner.id, ChatMessage.id == pk
        )
    )
    if row is None:
        return None, -1
    for index, item in enumerate(row.choices or ()):
        if item.get("kind") == CHANGE_KIND and item.get("key") == key:
            return row, index
    return row, -1


def _write(db: Session, row: ChatMessage, index: int, **fields: Any) -> None:
    items = [dict(item) for item in row.choices or ()]
    items[index] |= fields
    db.execute(
        update(ChatMessage).where(ChatMessage.id == row.id).values(choices=items)
    )
    row.choices = items


def confirm_change(
    db: Session, *, owner: User, message_id: str, key: str
) -> ChangeState:
    """The owner pressed the button: the campaigns screen's own service, checked again."""
    from app.modules.ads import actions

    row, index = _found(db, owner=owner, message_id=message_id, key=key)
    if row is None or index < 0:
        return ChangeState(state="gone", text=GONE_WORDS)
    item = row.choices[index]
    if item.get("state") != OPEN:
        return change_state(db, owner=owner, message_id=message_id, key=key)
    ask = _ask(str(item["action"]), str(item["level"]), str(item["external_id"]), item)
    log = actions.request(db, user=owner, ask=ask)
    _write(db, row, index, state=SENT, log_id=str(log.id))
    return ChangeState(state="working", text=WORKING)


def dismiss_change(
    db: Session, *, owner: User, message_id: str, key: str
) -> ChangeState:
    """The owner said no: the button goes, and nothing was ever sent."""
    row, index = _found(db, owner=owner, message_id=message_id, key=key)
    if row is None or index < 0:
        return ChangeState(state="gone", text=GONE_WORDS)
    if row.choices[index].get("state") != OPEN:
        return change_state(db, owner=owner, message_id=message_id, key=key)
    _write(db, row, index, state=DISMISSED)
    return ChangeState(state="dismissed", text="Bekor qilindi.")


def change_state(db: Session, *, owner: User, message_id: str, key: str) -> ChangeState:
    """Where the change has got to: still open, on its way, done or refused."""
    row, index = _found(db, owner=owner, message_id=message_id, key=key)
    if row is None or index < 0:
        return ChangeState(state="gone", text=GONE_WORDS)
    item = row.choices[index]
    if item.get("state") == OPEN:
        return ChangeState(state="open", text="")
    if item.get("state") == DISMISSED:
        return ChangeState(state="dismissed", text="Bekor qilindi.")
    try:
        log = db.get(ActionLog, uuid.UUID(str(item.get("log_id", ""))))
    except ValueError:
        log = None
    if log is None or log.owner_id != owner.id:
        return ChangeState(state="gone", text=GONE_WORDS)
    if log.status == ActionStatus.PENDING:
        return ChangeState(state="working", text=WORKING)
    if log.status == ActionStatus.APPLIED:
        landed = (log.result_payload or {}).get("landed")
        if landed is False:
            return ChangeState(state="done", text="O'zgarish Meta tomonida ko'rinmadi.")
        return ChangeState(state="done", text=APPLIED)
    return ChangeState(state="refused", text=_refused_words(db, log=log))


def _refused_words(db: Session, *, log: ActionLog) -> str:
    """The screen's own sentence, and the written answer under it when there is one.

    Never ``error_message``: that is the provider's text for the logs.
    """
    from app.common.i18n import get_language
    from app.modules.ads.selectors.actions import account_of, managed_target
    from app.modules.ads.selectors.failures import failure_sentence, unfamiliar
    from app.modules.chat.selectors.change_refusal import (
        change_explanation,
        change_links,
    )
    from core.chat.links import link_text

    sentence = failure_sentence(log) or FAILED_WORDS
    if not unfamiliar(log):
        return sentence
    text = change_explanation(db, log=log, language=get_language())
    if not text:
        return sentence
    target = managed_target(
        db, owner=log.owner, level=log.target_level, external_id=log.target_external_id
    )
    account = (
        account_of(target=target, level=log.target_level).external_id
        if target is not None
        else ""
    )
    return f"{sentence}\n\n{link_text(text, change_links(account))}"


__all__ = [
    "CHANGE_KIND",
    "ChangeState",
    "Prepared",
    "change_state",
    "confirm_change",
    "dismiss_change",
    "prepare_change",
]
