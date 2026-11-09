"""Leads into a Telegram group or channel: the cabinet's link, the bot's
two buttons, the bot added to a group or a channel, a public one refused,
one chat shared by two pairs, each lead posted once, Telegram's waits
retried, the bot removed and put back, and the sweep."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from telegramkit import (
    BotBlocked,
    ChatInfo,
    ChatMigrated,
    SentMessage,
    TelegramAPIError,
    TelegramRateLimited,
)

from app.common import tokens
from app.common.config import settings
from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.billing.models import Plan, Subscription
from app.modules.destinations import tasks as destination_tasks
from app.modules.destinations.models import LeadChat, LeadChatPair, LeadDelivery
from app.modules.destinations.services import lead_chats as lead_chats_module
from app.modules.destinations.services.lead_chats import (
    check_lead_chats,
    issue_lead_chat_link,
    post_lead,
    sweep_lead_posts,
)
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PagePair,
    ProviderConnection,
)
from app.modules.leads.models import Lead, LeadForm
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.services import (
    handle_staff_update,
    handle_support_update,
    handle_update,
)
from app.modules.notifications.services import respond as respond_module

ADDER = "5001"
GROUP = "-1001"
CHANNEL = "-1002"


class FakeBot:
    """Every call Telegram would have had."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.refuse: Exception | None = None
        self.chats: dict[str, ChatInfo] = {}

    def send_message(self, **fields: Any) -> SentMessage:
        self.calls.append(("send_message", fields))
        if self.refuse is not None:
            refusal, self.refuse = self.refuse, None
            raise refusal
        return SentMessage(message_id=1, chat_id=fields["chat_id"])

    def answer_callback_query(self, **fields: Any) -> None:
        self.calls.append(("answer_callback_query", fields))

    def get_chat(self, *, chat_id: str) -> ChatInfo:
        self.calls.append(("get_chat", {"chat_id": chat_id}))
        return self.chats.get(chat_id) or ChatInfo(id=chat_id, title="Lidlar")

    def leave_chat(self, *, chat_id: str) -> None:
        self.calls.append(("leave_chat", {"chat_id": chat_id}))

    def sent(self, chat_id: str) -> list[dict[str, Any]]:
        return [
            fields
            for name, fields in self.calls
            if name == "send_message" and fields["chat_id"] == chat_id
        ]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    client = FakeBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield client

    for module in (respond_module, lead_chats_module):
        monkeypatch.setattr(module, "bot", opened)
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s")
    monkeypatch.setattr(settings, "telegram_bot_username", "client_bot")
    monkeypatch.setattr(settings, "site_url", "https://app.example.test")
    return client


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(destination_tasks.post_lead_task, "delay", seen.append)
    return seen


def _auth(user: User) -> dict[str, str]:
    token = tokens.issue(subject=str(user.id), kind="access", now=utcnow())
    return {"Authorization": f"Bearer {token}"}


def _world(db: Session) -> dict[str, Any]:
    """Two pages on one account, each with a launch of ours, and a paid plan."""
    now = utcnow()
    owner = User(email="tg@example.com", full_name="Ega", password="!", date_joined=now)
    db.add(owner)
    db.flush()
    plan = Plan(price=100, max_adsets=10, llm_cost_limit_minor=0)
    db.add(plan)
    db.flush()
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=plan.id,
            status="active",
            started_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=29),
        )
    )
    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id="fb-1",
        token_encrypted=b"x",
        token_fingerprint=fingerprint("x"),
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="act_1",
        connection_id=connection.id,
        name="Asosiy",
        currency="USD",
        timezone="Asia/Tashkent",
        may_advertise=True,
        is_active=True,
        is_current=True,
    )
    pages = [
        PageAccount(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id=f"page_{n}",
            connection_id=connection.id,
            name=f"Sahifa {n}",
            token_encrypted=b"x",
            token_fingerprint=f"p{n}",
            is_active=True,
            is_current=n == 1,
        )
        for n in (1, 2)
    ]
    db.add_all([account, *pages])
    db.flush()
    forms = []
    for n, page in enumerate(pages, start=1):
        db.add(PagePair(owner_id=owner.id, page_id=page.id, ad_account_id=account.id))
        db.add(
            CampaignLaunch(
                owner_id=owner.id,
                ad_account_id=account.id,
                page_id=page.id,
                provider=PROVIDER,
                status="created",
                created_refs={"campaign": f"c_{n}"},
            )
        )
        form = LeadForm(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id=f"f_{n}",
            page_id=page.id,
            name=f"Forma {n}",
        )
        db.add(form)
        forms.append(form)
    db.commit()
    return {"owner": owner, "account": account, "pages": pages, "forms": forms}


def _lead(
    db: Session, world: dict[str, Any], name: str, campaign: str, *, ago: int = 0
) -> Lead:
    owner, form = world["owner"], world["forms"][0 if campaign != "c_2" else 1]
    at = utcnow() - timedelta(minutes=ago)
    row = Lead(
        owner_id=owner.id,
        provider=PROVIDER,
        leadgen_id=name,
        form_id=form.id,
        campaign_external_id=campaign,
        phone_e164="+998901234567",
        full_name=name,
        field_data_raw=[{"name": "qachon", "values": ["Ertaga <tushdan keyin>"]}],
        submitted_at=at,
        received_at=at,
    )
    db.add(row)
    db.commit()
    return row


def _start(argument: str, *, sender: str = ADDER) -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": int(sender), "type": "private"},
            "from": {"id": int(sender), "first_name": "Ali"},
            "text": f"/start {argument}",
        },
    }


def _joined(
    chat_id: str,
    chat_type: str,
    *,
    status: str = "member",
    sender: str = ADDER,
    public: bool = False,
    can_post: bool = False,
) -> dict[str, Any]:
    chat: dict[str, Any] = {"id": int(chat_id), "type": chat_type, "title": "Lidlar"}
    if public:
        chat["username"] = "ochiq_guruh"
    member: dict[str, Any] = {"status": status, "user": {"id": 1, "is_bot": True}}
    if can_post:
        member["can_post_messages"] = True
    return {
        "update_id": 2,
        "my_chat_member": {
            "chat": chat,
            "from": {"id": int(sender), "first_name": "Ali"},
            "date": 0,
            "old_chat_member": {"status": "left", "user": {"id": 1, "is_bot": True}},
            "new_chat_member": member,
        },
    }


def _token_of(url: str) -> str:
    return url.rsplit("=", 1)[1]


def _open(db: Session, world: dict[str, Any], page: int = 0) -> str:
    """The cabinet's button, then /start in the bot: the token now waits."""
    pair = f"page_{page + 1}:act_1"
    token = _token_of(issue_lead_chat_link(db, owner=world["owner"], pair_key=pair))
    handle_update(db, payload=_start(token), now=utcnow())
    return token


def _link_group(db: Session, world: dict[str, Any], page: int = 0) -> LeadChat:
    _open(db, world, page)
    handle_update(db, payload=_joined(GROUP, "supergroup"), now=utcnow())
    return db.scalars(select(LeadChat).where(LeadChat.chat_id == GROUP)).one()


def test_the_bot_asks_group_or_channel_and_a_group_is_linked(
    db: Session, fake: FakeBot
) -> None:
    world = _world(db)
    url = issue_lead_chat_link(db, owner=world["owner"], pair_key="page_1:act_1")
    assert url.startswith("https://t.me/client_bot?start=lc_")
    token = _token_of(url)

    assert handle_update(db, payload=_start(token), now=utcnow()) == "lead_chat_offered"
    offer = fake.sent(ADDER)[-1]
    assert "Sahifa 1 · Asosiy" in offer["text"]
    urls = [button.url for button in offer["buttons"]]
    assert urls == [
        f"https://t.me/client_bot?startgroup={token}",
        "https://t.me/client_bot?startchannel&admin=post_messages",
    ]

    assert (
        handle_update(db, payload=_joined(GROUP, "supergroup"), now=utcnow())
        == "lead_chat_linked"
    )
    chat = db.scalars(select(LeadChat)).one()
    assert (chat.chat_id, chat.kind, chat.status) == (GROUP, "group", "active")
    seat = db.scalars(select(LeadChatPair)).one()
    assert seat.page_id == world["pages"][0].id
    assert "Sahifa 1 · Asosiy" in fake.sent(GROUP)[-1]["text"]
    assert "Ulandi" in fake.sent(ADDER)[-1]["text"]

    # The group's own /start with the same token, right after: spent, silent.
    group_start = _start(token)
    group_start["message"]["chat"] = {"id": int(GROUP), "type": "supergroup"}
    before = len(fake.calls)
    assert handle_update(db, payload=group_start, now=utcnow()) == "lead_chat_expired"
    assert not [c for c in fake.calls[before:] if c[0] == "send_message"]


def test_a_public_group_is_refused_and_left(db: Session, fake: FakeBot) -> None:
    world = _world(db)
    _open(db, world)

    outcome = handle_update(
        db, payload=_joined(GROUP, "supergroup", public=True), now=utcnow()
    )

    assert outcome == "lead_chat_public"
    assert ("leave_chat", {"chat_id": GROUP}) in fake.calls
    assert "ochiq" in fake.sent(ADDER)[-1]["text"]
    assert db.scalar(select(func.count()).select_from(LeadChat)) == 0


def test_a_channel_links_once_the_bot_may_post(db: Session, fake: FakeBot) -> None:
    world = _world(db)
    _open(db, world)

    no_rights = _joined(CHANNEL, "channel", status="administrator")
    assert handle_update(db, payload=no_rights, now=utcnow()) == "lead_chat_no_rights"
    assert "huquq" in fake.sent(ADDER)[-1]["text"]

    allowed = _joined(CHANNEL, "channel", status="administrator", can_post=True)
    assert handle_update(db, payload=allowed, now=utcnow()) == "lead_chat_linked"
    assert db.scalars(select(LeadChat)).one().kind == "channel"


def test_a_second_pair_picks_the_group_already_linked(
    db: Session, fake: FakeBot
) -> None:
    world = _world(db)
    chat = _link_group(db, world, page=0)

    _open(db, world, page=1)
    offer = fake.sent(ADDER)[-1]
    pick = next(button for button in offer["buttons"] if button.data)
    assert pick.data == f"lc:{chat.id.hex}"
    press = {
        "update_id": 3,
        "callback_query": {
            "id": "q1",
            "from": {"id": int(ADDER)},
            "data": pick.data,
            "message": {"message_id": 9, "chat": {"id": int(ADDER), "type": "private"}},
        },
    }
    assert handle_update(db, payload=press, now=utcnow()) == "lead_chat_linked"

    seats = list(db.scalars(select(LeadChatPair)))
    assert len(seats) == 2
    assert {seat.lead_chat_id for seat in seats} == {chat.id}


def test_each_lead_is_posted_once_to_its_own_pair_s_chat(
    db: Session, fake: FakeBot
) -> None:
    world = _world(db)
    old = _lead(db, world, "eski", "c_1", ago=60)
    _link_group(db, world, page=0)
    mine = _lead(db, world, "Ali", "c_1")
    other_pair = _lead(db, world, "Vali", "c_2")
    ads_manager = _lead(db, world, "Begona", "c_9")

    assert post_lead(db, lead_id=str(mine.id), now=utcnow()) == "posted"
    post = fake.sent(GROUP)[-1]
    assert "Ali" in post["text"] and "+998901234567" in post["text"]
    assert "Ertaga &lt;tushdan keyin&gt;" in post["text"]
    assert "Forma 1" in post["text"]
    assert post["buttons"][0].url == f"https://app.example.test/app/leads/{mine.id}/"

    assert post_lead(db, lead_id=str(mine.id), now=utcnow()) == "already"
    assert post_lead(db, lead_id=str(old.id), now=utcnow()) == "skipped"
    assert post_lead(db, lead_id=str(other_pair.id), now=utcnow()) == "skipped"
    assert post_lead(db, lead_id=str(ads_manager.id), now=utcnow()) == "skipped"
    assert len([p for p in fake.sent(GROUP) if "Yangi lid" in p["text"]]) == 1
    delivery = db.scalars(select(LeadDelivery)).one()
    assert (delivery.channel, delivery.status) == ("telegram", "delivered")


def test_telegram_s_wait_gives_the_lead_back(db: Session, fake: FakeBot) -> None:
    world = _world(db)
    _link_group(db, world)
    lead = _lead(db, world, "Ali", "c_1")

    fake.refuse = TelegramRateLimited("Too Many Requests", code=429, retry_after=17)
    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == 17
    assert db.scalar(select(func.count()).select_from(LeadDelivery)) == 0

    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == "posted"


def test_a_supergroup_keeps_its_leads_under_the_new_id(
    db: Session, fake: FakeBot
) -> None:
    world = _world(db)
    _link_group(db, world)
    lead = _lead(db, world, "Ali", "c_1")

    fake.refuse = ChatMigrated("upgraded", code=400, migrate_to_chat_id="-1009")
    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == 0
    assert db.scalars(select(LeadChat)).one().chat_id == "-1009"

    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == "posted"
    assert fake.sent("-1009")


def test_the_bot_removed_stops_the_chat_and_tells_the_owner(
    db: Session, fake: FakeBot
) -> None:
    world = _world(db)
    db.add(TelegramChat(owner_id=world["owner"].id, chat_id="7000", linked_at=utcnow()))
    db.commit()
    _link_group(db, world)
    lead = _lead(db, world, "Ali", "c_1")

    fake.refuse = BotBlocked("Forbidden: bot was kicked from the supergroup chat")
    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == "broken"
    chat = db.scalars(select(LeadChat)).one()
    assert (chat.status, chat.broken_reason) == ("broken", "removed")
    assert "tushmay qoldi" in fake.sent("7000")[-1]["text"]
    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == "skipped"

    # Somebody puts the bot back: posting starts again.
    back = handle_update(db, payload=_joined(GROUP, "supergroup"), now=utcnow())
    assert back == "lead_chat_mended"
    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == "posted"


def test_removed_from_the_group_and_rights_refused(db: Session, fake: FakeBot) -> None:
    world = _world(db)
    _link_group(db, world)

    left = handle_update(
        db, payload=_joined(GROUP, "supergroup", status="kicked"), now=utcnow()
    )
    assert left == "lead_chat_broken"
    assert db.scalars(select(LeadChat)).one().broken_reason == "removed"

    handle_update(db, payload=_joined(GROUP, "supergroup"), now=utcnow())
    lead = _lead(db, world, "Ali", "c_1")
    fake.refuse = TelegramAPIError(
        "Bad Request: not enough rights to send text messages to the chat"
    )
    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == "broken"
    assert db.scalars(select(LeadChat)).one().broken_reason == "rights"


def test_commands_in_a_group_are_not_answered(db: Session, fake: FakeBot) -> None:
    payload = _start("")
    payload["message"]["chat"] = {"id": int(GROUP), "type": "supergroup"}
    payload["message"]["text"] = "/hisobot"

    assert handle_update(db, payload=payload, now=utcnow()) == "ignored"
    assert not fake.calls


def test_the_sweep_queues_what_was_never_posted(
    db: Session, fake: FakeBot, queued: list[str]
) -> None:
    world = _world(db)
    chat = _link_group(db, world)
    db.execute(
        LeadChatPair.__table__.update().values(linked_at=utcnow() - timedelta(hours=2))
    )
    chat.linked_at = utcnow() - timedelta(hours=2)
    db.commit()
    lost = _lead(db, world, "Ali", "c_1", ago=30)
    posted = _lead(db, world, "Vali", "c_1", ago=20)
    _lead(db, world, "Hali", "c_1")  # just arrived: its own task runs first
    _lead(db, world, "Begona", "c_9", ago=30)
    assert post_lead(db, lead_id=str(posted.id), now=utcnow()) == "posted"

    assert sweep_lead_posts(db, now=utcnow()) == 1
    assert queued == [str(lost.id)]


def test_the_panel_unlink_and_remove(
    client: TestClient, db: Session, fake: FakeBot
) -> None:
    world = _world(db)
    chat = _link_group(db, world)
    auth = _auth(world["owner"])

    panel = client.get("/api/v1/destinations/telegram", headers=auth).json()
    assert panel["enabled"] is True
    assert [(p["key"], p["chat"]) for p in panel["pairs"]] == [
        ("page_1:act_1", str(chat.id)),
        ("page_2:act_1", ""),
    ]
    assert panel["chats"][0]["pairs"] == ["page_1:act_1"]
    assert panel["chats"][0]["kindLabel"] == "Guruh"

    link = client.post(
        "/api/v1/destinations/telegram/link",
        json={"pair": "page_2:act_1"},
        headers=auth,
    )
    assert link.status_code == 200 and "start=lc_" in link.json()["url"]
    missing = client.post(
        "/api/v1/destinations/telegram/link",
        json={"pair": "page_9:act_1"},
        headers=auth,
    )
    assert missing.status_code == 404

    unlinked = client.delete(
        "/api/v1/destinations/telegram/pairs/page_1:act_1", headers=auth
    ).json()
    assert unlinked["pairs"][0]["chat"] == ""
    assert unlinked["chats"][0]["pairs"] == []

    removed = client.delete(
        f"/api/v1/destinations/telegram/chats/{chat.id}", headers=auth
    ).json()
    assert removed["chats"] == []
    assert ("leave_chat", {"chat_id": GROUP}) in fake.calls


def test_a_supergroup_already_linked_takes_the_old_group_s_pairs(
    db: Session, fake: FakeBot
) -> None:
    world = _world(db)
    old = _link_group(db, world, page=0)
    _open(db, world, page=1)
    handle_update(db, payload=_joined("-1009", "supergroup"), now=utcnow())
    lead = _lead(db, world, "Ali", "c_1")

    fake.refuse = ChatMigrated("upgraded", code=400, migrate_to_chat_id="-1009")
    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == 0

    chats = list(db.scalars(select(LeadChat)))
    assert [c.chat_id for c in chats] == ["-1009"]
    assert {seat.lead_chat_id for seat in db.scalars(select(LeadChatPair))} == {
        chats[0].id
    }
    assert db.get(LeadChat, old.id) is None
    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == "posted"


def test_a_chat_made_public_later_stops_at_the_hourly_look(
    db: Session, fake: FakeBot
) -> None:
    world = _world(db)
    db.add(TelegramChat(owner_id=world["owner"].id, chat_id="7000", linked_at=utcnow()))
    db.commit()
    _link_group(db, world)
    later = utcnow() + timedelta(hours=2)

    assert check_lead_chats(db, now=utcnow()) == 0  # looked at when linked
    fake.chats[GROUP] = ChatInfo(id=GROUP, title="Lidlar", username="ochiq")
    assert check_lead_chats(db, now=later) == 1

    chat = db.scalars(select(LeadChat)).one()
    assert (chat.status, chat.broken_reason) == ("broken", "public")
    assert "ochiq" in fake.sent("7000")[-1]["text"]
    lead = _lead(db, world, "Ali", "c_1")
    assert post_lead(db, lead_id=str(lead.id), now=utcnow()) == "skipped"


def test_a_restricted_bot_that_may_still_send_stays(db: Session, fake: FakeBot) -> None:
    world = _world(db)
    _link_group(db, world)
    payload = _joined(GROUP, "supergroup", status="restricted")
    member = payload["my_chat_member"]["new_chat_member"]
    member.update(is_member=True, can_send_messages=True)

    assert handle_update(db, payload=payload, now=utcnow()) == "ignored"
    assert db.scalars(select(LeadChat)).one().status == "active"

    member["can_send_messages"] = False
    assert handle_update(db, payload=payload, now=utcnow()) == "lead_chat_broken"


def test_the_other_bots_ignore_their_own_membership(db: Session) -> None:
    blocked = _joined(ADDER, "private", status="kicked")

    assert handle_support_update(db, payload=blocked, now=utcnow()) == "ignored"
    assert handle_staff_update(db, payload=blocked, now=utcnow()) == "ignored"
