"""A campaign on an account Meta switched off is not drawn as running.

Meta keeps the campaign ACTIVE: the switch is the campaign's, the stop is
the account's. The customer's list and the office both say whose stop it is
and leave the campaign out of what runs.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.models import Campaign
from app.modules.backoffice.selectors.delivery import running_clause
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors.standing import stopped_kind
from tests.pg.test_campaigns_contract import _cabinet_with_figures
from tests.pg.test_office_ads import _launched
from tests.pg.test_office_ads_state import _fresh, _list


def _account(db: Session, campaign: Any) -> AdAccount:
    account = db.get(AdAccount, campaign.ad_account_id)
    assert account is not None
    return account


def _stop(db: Session, account: AdAccount, **values: Any) -> None:
    for name, value in values.items():
        setattr(account, name, value)
    db.commit()


@pytest.mark.parametrize(
    ("values", "kind"),
    [
        ({"may_advertise": None, "standing": ""}, None),
        ({"may_advertise": True, "standing": "active"}, None),
        ({"may_advertise": True, "standing": "payment_grace"}, None),
        ({"may_advertise": True, "standing": "review"}, None),
        ({"may_advertise": False, "standing": "disabled"}, "disabled"),
        ({"may_advertise": False, "standing": "closed"}, "closed"),
        ({"may_advertise": False, "standing": "", "account_status": "101"}, "closed"),
        ({"may_advertise": False, "standing": "", "account_status": "2"}, "disabled"),
        ({"may_advertise": False, "standing": "disabled_payment"}, "payment"),
        ({"may_advertise": False, "standing": "payment_failed"}, "payment"),
        ({"may_advertise": False, "payment_due": True, "standing": ""}, "payment"),
    ],
)
def test_what_an_account_says_of_itself(values: dict, kind: str | None) -> None:
    account = AdAccount(**{"account_status": "1", "payment_due": False, **values})

    assert stopped_kind(account) == kind


def test_a_working_account_marks_nothing(client: TestClient, db: Session) -> None:
    headers, _campaign = _cabinet_with_figures(client, db)

    body = client.get("/api/v1/campaigns", headers=headers).json()

    assert body["stoppedAccounts"] == []
    assert body["campaigns"][0]["accountStopped"] is None
    assert body["counts"]["accountStopped"] == 0


def test_the_list_says_the_account_is_switched_off(
    client: TestClient, db: Session
) -> None:
    headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    _stop(db, account, may_advertise=False, standing="disabled", account_status="2")

    body = client.get("/api/v1/campaigns", headers=headers).json()

    [told] = body["stoppedAccounts"]
    assert told["externalId"] == account.external_id
    assert told["kind"] == "disabled"
    assert told["href"] and "accountquality" in told["href"]
    row = body["campaigns"][0]
    assert row["accountStopped"] == "disabled"
    # Meta's own word is kept: it is what Meta says of the campaign.
    assert row["status"] in ("active", "learning")
    assert body["counts"]["accountStopped"] == body["counts"]["running"] >= 1


def test_an_unpaid_account_sends_its_owner_to_the_bill(
    client: TestClient, db: Session
) -> None:
    headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    _stop(
        db,
        account,
        may_advertise=False,
        payment_due=True,
        standing="payment_failed",
        account_status="3",
    )

    body = client.get("/api/v1/campaigns", headers=headers).json()

    [told] = body["stoppedAccounts"]
    assert told["kind"] == "payment"
    assert told["href"] and "billing" in told["href"]
    assert body["campaigns"][0]["accountStopped"] == "payment"


def test_a_switched_off_campaign_is_not_counted_twice(
    client: TestClient, db: Session
) -> None:
    headers, campaign = _cabinet_with_figures(client, db)
    _stop(db, _account(db, campaign), may_advertise=False, standing="closed")
    for row in db.scalars(select(Campaign).where(Campaign.id == campaign.id)):
        row.delivery = "paused"
        row.status = "PAUSED"
    db.commit()

    body = client.get("/api/v1/campaigns", headers=headers).json()

    assert body["stoppedAccounts"][0]["kind"] == "closed"
    assert body["counts"]["accountStopped"] == 0


def test_the_office_does_not_call_a_blocked_accounts_campaign_running(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    account = _fresh(db, launch)
    assert _list(client, owner, headers)["running"] == 1
    _stop(db, account, may_advertise=False, standing="disabled", account_status="2")

    body = _list(client, owner, headers)

    [row] = body["rows"]
    assert (row["delivery"], row["delivery_label"], row["is_running"]) == (
        "account_blocked",
        "Akkaunt bloklangan",
        False,
    )
    assert body["running"] == 0


def test_the_office_reads_an_unpaid_account_as_billing(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    account = _fresh(db, launch)
    _stop(db, account, may_advertise=False, payment_due=True, standing="payment_failed")

    [row] = _list(client, owner, headers)["rows"]

    assert (row["delivery"], row["is_running"]) == ("billing", False)


def test_the_offices_running_count_leaves_a_blocked_account_out(
    client: TestClient, db: Session
) -> None:
    owner, launch, _headers = _launched(client, db)
    account = _fresh(db, launch)
    now = utcnow()

    def running() -> int:
        return int(
            db.scalar(
                select(func.count(Campaign.id)).where(
                    Campaign.owner_id == owner.id, running_clause(now=now)
                )
            )
            or 0
        )

    assert running() == 1
    _stop(db, account, may_advertise=False, standing="closed")
    assert running() == 0
    _stop(db, account, may_advertise=None, standing="disabled")
    assert running() == 0
    _stop(db, account, may_advertise=True, standing="active")
    assert running() == 1


# -- the exact cause -------------------------------------------------------------------


def _blocked(**values: Any) -> AdAccount:
    return AdAccount(
        **{
            "provider": "meta",
            "external_id": "act_77",
            "name": "Do'kon",
            "account_status": "2",
            "payment_due": False,
            "may_advertise": False,
            "standing": "disabled",
            **values,
        }
    )


@pytest.mark.parametrize(
    ("values", "reason", "said", "door"),
    [
        (
            {"disable_reason": "1"},
            "ADS_INTEGRITY_POLICY",
            "qoidalari",
            "accountquality",
        ),
        (
            {"disable_reason": "15"},
            "COMPROMISED_AD_ACCOUNT",
            "begona",
            "accountquality",
        ),
        ({"disable_reason": "9"}, "UNUSED_ACCOUNT", "ishlatilmagani", "adsmanager"),
        (
            {"disable_reason": "11"},
            "BUSINESS_MANAGER_INTEGRITY_POLICY",
            "portfel",
            "accountquality",
        ),
        # Named by Meta and not explained: said under Meta's own name.
        (
            {"disable_reason": "4"},
            "GRAY_ACCOUNT_SHUT_DOWN",
            "«GRAY_ACCOUNT_SHUT_DOWN»",
            "accountquality",
        ),
        ({"disable_reason": ""}, "", "sababini ko'rsatmagan", "accountquality"),
        ({"disable_reason": "0"}, "", "sababini ko'rsatmagan", "accountquality"),
        (
            {"disable_reason": "3", "standing": "disabled_payment"},
            "RISK_PAYMENT",
            "to'lov bilan bog'liq xavf",
            "billing",
        ),
        (
            {"standing": "payment_failed", "account_status": "3", "payment_due": True},
            "",
            "yecha olmagan",
            "billing",
        ),
        (
            {"standing": "closed", "account_status": "101", "disable_reason": "7"},
            "PERMANENT_CLOSE",
            "butunlay yopgan",
            "adsmanager",
        ),
        ({"standing": "closed", "account_status": "101"}, "", "yopilgan", "adsmanager"),
        (
            {"standing": "closed", "account_status": "100"},
            "",
            "yopilish jarayonida",
            "adsmanager",
        ),
    ],
)
def test_metas_reason_is_said_as_it_is(
    values: dict, reason: str, said: str, door: str
) -> None:
    from app.modules.integrations.block_causes import block_cause

    cause = block_cause(_blocked(**values))

    assert cause is not None
    assert cause.reason == reason
    assert said in cause.cause
    assert door in cause.href
    assert "Do'kon" in cause.title and cause.fix and cause.action


def test_every_reason_meta_publishes_has_words() -> None:
    from app.modules.integrations.block_causes import REASON_NAMES, block_cause

    for number, name in REASON_NAMES.items():
        cause = block_cause(_blocked(disable_reason=number))
        assert cause is not None and cause.reason == name and cause.cause


def test_a_working_account_has_no_cause() -> None:
    from app.modules.integrations.block_causes import block_cause

    assert block_cause(_blocked(may_advertise=True, standing="active")) is None


def test_the_inbox_line_says_why(client: TestClient, db: Session) -> None:
    from app.modules.notifications.selectors.inbox_meta import meta_items

    headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    _stop(
        db,
        account,
        may_advertise=False,
        standing="disabled",
        account_status="2",
        disable_reason="15",
    )

    [item] = [
        one
        for one in meta_items(db, owner=account.owner, accounts=[account])
        if one.kind == "account_blocked"
    ]

    assert "bloklagan" in item.title
    assert "begona odam kirgan" in item.body
    assert "hech kimga ko'rsatilmayapti" in item.body
    assert "accountquality" in item.href
    body = client.get("/api/v1/campaigns", headers=headers).json()
    [told] = body["stoppedAccounts"]
    assert told["reason"] == "COMPROMISED_AD_ACCOUNT"
    assert "begona odam kirgan" in told["cause"] and told["fix"]
    assert "accountquality" in told["href"]


# -- the account is asked before its lists ---------------------------------------------


def _state(account: AdAccount, **values: Any) -> Any:
    from adskit.dto import AccountStateDTO
    from adskit.refs import ExternalRef

    return AccountStateDTO(
        ref=ExternalRef(provider="meta", level="account", id=account.external_id),
        **values,
    )


def test_a_block_is_stored_though_meta_refuses_the_lists(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ads.exceptions import SyncFailed
    from app.modules.ads.services import mirror, stops

    _headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    asked: list[str] = []

    def state(_account: AdAccount) -> Any:
        asked.append("account")
        return _state(account, standing="disabled", raw_status="2", raw_reason="1")

    def lists(*_args: Any, **_kwargs: Any) -> Any:
        asked.append("lists")
        raise SyncFailed

    monkeypatch.setattr(stops, "read_account_state", state)
    monkeypatch.setattr(mirror, "read_everything", lists)

    with pytest.raises(SyncFailed):
        mirror.sync_ad_account(db, ad_account=account)

    db.expire_all()
    account = _account(db, campaign)
    assert asked == ["account", "lists"]
    assert (account.standing, account.may_advertise) == ("disabled", False)
    assert (account.account_status, account.disable_reason) == ("2", "1")
    assert stopped_kind(account) == "disabled"
    # The lock is given back: the next sweep reads the account again.
    assert mirror.cache.add(mirror.mirror_lock_key(account), "1", 1) is True
    mirror.cache.delete(mirror.mirror_lock_key(account))


def test_an_account_meta_did_not_answer_for_keeps_what_was_known(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ads.exceptions import SyncFailed
    from app.modules.ads.services import mirror, stops

    _headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    _stop(db, account, may_advertise=True, standing="active")
    monkeypatch.setattr(stops, "read_account_state", lambda _account: None)

    def lists(*_args: Any, **_kwargs: Any) -> Any:
        raise SyncFailed

    monkeypatch.setattr(mirror, "read_everything", lists)

    with pytest.raises(SyncFailed):
        mirror.sync_ad_account(db, ad_account=account)

    db.expire_all()
    account = _account(db, campaign)
    assert (account.standing, account.may_advertise) == ("active", True)


# -- the campaign's page and the Expert table say what the list says -------------------


def _detail(client: TestClient, headers: dict, campaign: Any) -> dict:
    answer = client.get(f"/api/v2/campaigns/{campaign.id}", headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


def _expert(client: TestClient, headers: dict) -> dict:
    answer = client.get("/api/v2/campaigns/expert?period=7d", headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_a_fresh_campaign_carries_no_mark_anywhere(
    client: TestClient, db: Session
) -> None:
    headers, campaign = _cabinet_with_figures(client, db)
    for row in db.scalars(select(Campaign).where(Campaign.id == campaign.id)):
        row.synced_at = utcnow()
    db.commit()

    page = _detail(client, headers, campaign)
    table = _expert(client, headers)
    row = client.get("/api/v1/campaigns", headers=headers).json()["campaigns"][0]

    for told in (page, row, *table["campaigns"], *table["adsets"], *table["ads"]):
        assert told["frozenSince"] is None
        assert told["staleSince"] is None
        assert told["accountStopped"] is None
    assert page["disconnected"] is None and page["stoppedAccount"] is None


def test_the_page_and_the_table_say_the_account_is_switched_off(
    client: TestClient, db: Session
) -> None:
    headers, campaign = _cabinet_with_figures(client, db)
    _stop(
        db,
        _account(db, campaign),
        may_advertise=False,
        standing="disabled",
        account_status="2",
        disable_reason="1",
    )

    page = _detail(client, headers, campaign)
    table = _expert(client, headers)

    assert page["accountStopped"] == "disabled"
    assert page["stoppedAccount"]["reason"] == "ADS_INTEGRITY_POLICY"
    assert "qoidalari" in page["stoppedAccount"]["cause"]
    assert table["campaigns"] and all(
        row["accountStopped"] == "disabled"
        for name in ("campaigns", "adsets", "ads")
        for row in table[name]
    )


def test_a_campaign_not_read_for_long_is_said_to_be_old(
    client: TestClient, db: Session
) -> None:
    from datetime import timedelta

    headers, campaign = _cabinet_with_figures(client, db)
    old = utcnow() - timedelta(days=4)
    for row in db.scalars(select(Campaign).where(Campaign.id == campaign.id)):
        row.synced_at = old
        row.delivery = "active"
    db.commit()

    body = client.get("/api/v1/campaigns", headers=headers).json()
    page = _detail(client, headers, campaign)
    table = _expert(client, headers)

    assert body["campaigns"][0]["staleSince"] == old.isoformat()
    assert body["counts"]["stale"] == 1
    assert page["staleSince"] == old.isoformat()
    assert table["campaigns"][0]["staleSince"] == old.isoformat()

    # Switched off: its word holds however old the copy is.
    for row in db.scalars(select(Campaign).where(Campaign.id == campaign.id)):
        row.delivery = "paused"
        row.status = "PAUSED"
    db.commit()
    body = client.get("/api/v1/campaigns", headers=headers).json()
    assert body["campaigns"][0]["staleSince"] is None
    assert body["counts"]["stale"] == 0


def test_the_page_and_the_table_say_the_connection_is_dead(
    client: TestClient, db: Session
) -> None:
    from app.modules.integrations.constants import ConnectionStatus

    headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    account.connection.status = ConnectionStatus.INVALID
    db.commit()

    page = _detail(client, headers, campaign)
    table = _expert(client, headers)

    assert page["frozenSince"] is not None
    assert page["disconnected"]["status"] == "invalid"
    # Frozen says it already: one mark, not two.
    assert page["staleSince"] is None
    assert table["campaigns"][0]["frozenSince"] is not None


# -- the last words that guessed --------------------------------------------------------


def test_the_five_codes_read_on_production_have_their_own_words() -> None:
    from app.modules.ads.selectors.delivery_issues import TROUBLES

    for code, said in {
        "1487083": "saqlay olmadi",
        "1487891": "maqsadga mos emas",
        "1443073": "lid formasi",
        "2490424": "vaqtincha to'xtatdi",
        "2875003": "Instagram'da ishlamaydi",
    }.items():
        assert said in TROUBLES[code].title
        assert TROUBLES[code].cause and TROUBLES[code].steps


def test_a_refused_change_on_a_hacked_account_does_not_send_to_the_bill() -> None:
    from types import SimpleNamespace

    from app.modules.ads.selectors.failures import failure_note

    account = _blocked(disable_reason="15")
    campaign = SimpleNamespace(ad_account=account)
    action = SimpleNamespace(error_code="account_blocked", result_payload={})

    note = failure_note(action=action, target=campaign, level="campaign")

    assert "begona odam kirgan" in note.sentence
    assert "qarz" not in note.sentence
    assert "accountquality" in note.fix_url


def test_a_refused_change_on_an_unpaid_account_still_sends_to_the_bill() -> None:
    from types import SimpleNamespace

    from app.modules.ads.selectors.failures import failure_note

    account = _blocked(standing="payment_failed", account_status="3", payment_due=True)
    action = SimpleNamespace(error_code="account_blocked", result_payload={})

    note = failure_note(
        action=action, target=SimpleNamespace(ad_account=account), level="campaign"
    )

    assert "yecha olmagan" in note.sentence and "billing" in note.fix_url


# -- found on review --------------------------------------------------------------------


def test_a_watched_account_read_last_night_is_not_called_old(
    client: TestClient, db: Session
) -> None:
    """It is read once a night: three hours would call it old all day."""
    from datetime import timedelta

    _headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)

    def stale_at(hours: int, *, chosen: bool) -> Any:
        account.is_active = chosen
        for row in db.scalars(select(Campaign).where(Campaign.id == campaign.id)):
            row.synced_at = utcnow() - timedelta(hours=hours)
            row.delivery = "active"
        db.commit()
        from app.modules.ads.selectors.row_marks import campaign_marks

        row = db.get(Campaign, campaign.id)
        return campaign_marks(db, campaigns=[row])[row.external_id].stale_since

    assert stale_at(20, chosen=False) is None
    assert stale_at(40, chosen=False) is not None
    assert stale_at(20, chosen=True) is not None
    assert stale_at(1, chosen=True) is None


def test_another_networks_account_is_not_said_in_metas_words() -> None:
    from app.modules.integrations.block_causes import block_cause

    cause = block_cause(_blocked(provider="google", disable_reason="1", name="Shop"))

    assert cause is not None and cause.kind == "disabled"
    assert "Google Ads" in cause.cause and "Meta" not in cause.body
    assert cause.reason == "" and cause.href == "" and cause.action == ""


def test_the_inbox_offers_no_button_that_leads_nowhere(
    client: TestClient, db: Session
) -> None:
    from app.modules.notifications.selectors.inbox_meta import meta_items

    _headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    _stop(db, account, may_advertise=False, standing="disabled", provider="google")

    [item] = [
        one
        for one in meta_items(db, owner=account.owner, accounts=[account])
        if one.kind == "account_blocked"
    ]

    assert item.href == "" and item.action == ""
    assert "Meta" not in item.title + item.body


def test_the_refusal_dialog_names_the_accounts_own_cause() -> None:
    from types import SimpleNamespace

    from app.modules.ads.selectors.failures import failure_note, note_refusal

    account = _blocked(disable_reason="15")
    action = SimpleNamespace(error_code="account_blocked", result_payload={})
    note = failure_note(
        action=action, target=SimpleNamespace(ad_account=account), level="campaign"
    )

    told = note_refusal(note=note, action=action, key="")

    assert "begona odam kirgan" in told.cause
    assert all("qarz" not in step.lower() for step in told.steps) and told.steps
    assert told.fix is not None and "accountquality" in told.fix.url


def test_the_ai_is_told_metas_reason() -> None:
    from app.modules.assistant.selectors.health import _metas_reason
    from app.modules.chat.selectors.lookups.accounts import _why

    account = _blocked(disable_reason="12")

    assert "MISREPRESENTED_AD_ACCOUNT" in _metas_reason(account)
    assert "MISREPRESENTED_AD_ACCOUNT" in _why(account)
    assert _why(_blocked(may_advertise=None, standing="")) == ""


def test_the_showcase_never_goes_old(client: TestClient, db: Session) -> None:
    """Nothing reads it: three hours after it was made it must still say on."""
    from datetime import timedelta

    from app.modules.ads.selectors.row_marks import campaign_marks
    from app.modules.integrations.constants import ConnectionStatus

    _headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    account.connection.status = ConnectionStatus.DEMO
    for row in db.scalars(select(Campaign).where(Campaign.id == campaign.id)):
        row.synced_at = utcnow() - timedelta(days=9)
        row.delivery = "active"
    db.commit()

    row = db.get(Campaign, campaign.id)
    mark = campaign_marks(db, campaigns=[row])[row.external_id]

    assert mark.stale_since is None and mark.frozen_since is None


# -- the phone and the dashboard are told too -------------------------------------------


def _phone(monkeypatch: pytest.MonkeyPatch, db: Session, account: AdAccount) -> Any:
    from app.common.config import settings
    from app.modules.billing.selectors import has_live_subscription
    from app.modules.billing.services import start_trial
    from app.modules.notifications.models import TelegramChat
    from tests.pg.test_office_telegram import FakeBot

    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    monkeypatch.setattr(settings, "telegram_mandatory_notices", True)
    monkeypatch.setattr(settings, "site_url", "https://targetolog.test")
    # A notice is owed only under a live subscription.
    if not has_live_subscription(db, owner=account.owner):
        start_trial(db, user=account.owner, now=utcnow())
    db.add(
        TelegramChat(
            owner_id=account.owner_id, chat_id="700", is_active=True, linked_at=utcnow()
        )
    )
    db.commit()
    return FakeBot()


def test_a_block_is_told_on_the_phone_at_once_with_its_cause_and_door(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.notifications.selectors import chat_for
    from app.modules.notifications.services.announce_account import (
        announce_blocks,
        announce_troubles,
    )

    _headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    bot = _phone(monkeypatch, db, account)
    assert announce_blocks(db, client=bot, now=utcnow()) == 0

    _stop(
        db,
        account,
        may_advertise=False,
        standing="disabled",
        account_status="2",
        disable_reason="15",
    )

    assert announce_blocks(db, client=bot, now=utcnow()) == 1
    [text] = bot.texts()
    assert "bloklagan" in text and "begona odam kirgan" in text
    # Answered in the center, like every notice: the door is on its line there.
    assert "/app/amallar/?item=account_blocked" in text
    assert "Account Quality" in text and "accountquality" not in text

    # Once: neither the next quarter hour nor the morning's list says it again.
    assert announce_blocks(db, client=bot, now=utcnow()) == 0
    chat = chat_for(db, owner=account.owner)
    assert chat is not None
    announce_troubles(db, client=bot, chat=chat, now=utcnow())
    assert sum("bloklagan" in said for said in bot.texts()) == 1


def test_an_unpaid_account_is_left_to_the_stop_s_own_message(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.notifications.services.announce_account import announce_blocks

    _headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)
    bot = _phone(monkeypatch, db, account)
    _stop(db, account, may_advertise=False, standing="disabled_payment")

    assert announce_blocks(db, client=bot, now=utcnow()) == 0


def test_the_dashboard_says_the_account_is_switched_off(
    client: TestClient, db: Session
) -> None:
    headers, campaign = _cabinet_with_figures(client, db)
    account = _account(db, campaign)

    assert (
        client.get("/api/v1/metrics/numbers", headers=headers).json()[
            "stopped_accounts"
        ]
        == []
    )

    _stop(
        db,
        account,
        may_advertise=False,
        standing="disabled",
        account_status="2",
        disable_reason="1",
    )
    body = client.get("/api/v1/metrics/numbers", headers=headers).json()

    [told] = body["stopped_accounts"]
    assert told["external_id"] == account.external_id and told["kind"] == "disabled"
    assert told["reason"] == "ADS_INTEGRITY_POLICY"
    assert "qoidalari" in told["cause"] and "accountquality" in told["href"]
