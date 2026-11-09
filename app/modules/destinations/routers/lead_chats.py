"""«Telegramga uzatish»: a pair's leads into a Telegram group or channel."""

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.modules.accounts.models import User
from app.modules.destinations.constants import (
    LEAD_CHAT_BROKEN_LABELS,
    LEAD_CHAT_KIND_LABELS,
    LeadChatBroken,
    LeadChatKind,
)
from app.modules.destinations.schemas import (
    LeadChatLinkIn,
    LeadChatLinkOut,
    LeadChatOut,
    LeadChatPairOut,
    LeadChatPanelOut,
)
from app.modules.destinations.selectors.lead_chats import lead_chat_panel
from app.modules.destinations.services.lead_chats import (
    drop_lead_chat,
    issue_lead_chat_link,
    unlink_pair,
)
from app.modules.notifications.bot import is_configured

router = APIRouter(prefix="/destinations/telegram", tags=["destinations"])


def panel_out(db: Session, *, owner: User) -> LeadChatPanelOut:
    panel = lead_chat_panel(db, owner=owner)
    return LeadChatPanelOut(
        enabled=is_configured(),
        pairs=[
            LeadChatPairOut(
                key=row.pair.key,
                page_name=row.pair.page.name,
                account_name=row.pair.account.name,
                chat=str(row.chat.id) if row.chat is not None else "",
            )
            for row in panel.pairs
        ],
        chats=[
            LeadChatOut(
                pk=str(chat.id),
                title=chat.title,
                kind=chat.kind,
                kind_label=LEAD_CHAT_KIND_LABELS.get(LeadChatKind(chat.kind), ""),
                status=chat.status,
                reason=chat.broken_reason,
                reason_label=(
                    LEAD_CHAT_BROKEN_LABELS.get(LeadChatBroken(chat.broken_reason), "")
                    if chat.broken_reason
                    else ""
                ),
                linked_at=chat.linked_at,
                pairs=list(panel.pair_keys.get(str(chat.id), ())),
            )
            for chat in panel.chats
        ],
    )


@router.get("", response_model=LeadChatPanelOut)
def get_panel(db: Db, user: CurrentUser) -> LeadChatPanelOut:
    """Every pair and where its leads go, and the owner's groups and channels."""
    return panel_out(db, owner=user)


@router.post("/link", response_model=LeadChatLinkOut)
def start_link(body: LeadChatLinkIn, db: Db, user: CurrentUser) -> LeadChatLinkOut:
    """The bot link for one pair; it lives 30 minutes. 400 without a bot."""
    return LeadChatLinkOut(url=issue_lead_chat_link(db, owner=user, pair_key=body.pair))


@router.delete("/pairs/{pair}", response_model=LeadChatPanelOut)
def stop_pair(pair: str, db: Db, user: CurrentUser) -> LeadChatPanelOut:
    """This pair's leads stop going to Telegram. The chat stays for others."""
    unlink_pair(db, owner=user, pair_key=pair)
    return panel_out(db, owner=user)


@router.delete("/chats/{pk}", response_model=LeadChatPanelOut)
def remove_chat(pk: str, db: Db, user: CurrentUser) -> LeadChatPanelOut:
    """Forget the chat and every pair posting there; the bot leaves it."""
    drop_lead_chat(db, owner=user, chat_pk=pk)
    return panel_out(db, owner=user)
