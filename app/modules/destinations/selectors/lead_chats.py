"""What the «Telegramga uzatish» panel shows: every pair, where its leads go,
and the owner's groups and channels."""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.destinations.models import LeadChat, LeadChatPair
from app.modules.integrations.selectors import Pair, page_pairs


@dataclass(frozen=True, slots=True)
class PairRow:
    pair: Pair
    chat: LeadChat | None


@dataclass(frozen=True, slots=True)
class LeadChatPanel:
    pairs: tuple[PairRow, ...]
    chats: tuple[LeadChat, ...]
    pair_keys: dict[str, tuple[str, ...]]


def lead_chat_panel(db: Session, *, owner: User) -> LeadChatPanel:
    pairs = page_pairs(db, owner=owner)
    chats = list(
        db.scalars(
            select(LeadChat)
            .where(LeadChat.owner_id == owner.id)
            .order_by(LeadChat.linked_at.desc())
        )
    )
    by_id = {chat.id: chat for chat in chats}
    seats = {
        (seat.page_id, seat.ad_account_id): seat.lead_chat_id
        for seat in db.scalars(
            select(LeadChatPair).where(LeadChatPair.owner_id == owner.id)
        )
    }
    keys: dict[str, list[str]] = defaultdict(list)
    rows = []
    for pair in pairs:
        chat = by_id.get(seats.get((pair.page.id, pair.account.id)))  # type: ignore[arg-type]
        if chat is not None:
            keys[str(chat.id)].append(pair.key)
        rows.append(PairRow(pair=pair, chat=chat))
    return LeadChatPanel(
        pairs=tuple(rows),
        chats=tuple(chats),
        pair_keys={pk: tuple(found) for pk, found in keys.items()},
    )
