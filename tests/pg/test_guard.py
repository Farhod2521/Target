"""The half-hourly guard against PostgreSQL: a price said at five usual
prices - never at three or four - and stopped at ten, money gone with nothing back stopped,
nothing said twice, and a group switched back on counted from there."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.i18n import override
from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, CampaignLaunch
from app.modules.agent.constants import GUARD_STOP_MARK
from app.modules.agent.models import GuardAlert
from app.modules.agent.services.run_guard import run_guard
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.billing.services import start_trial
from app.modules.integrations.models import AdAccount
from app.modules.metrics.models import MetricsDaily
from app.modules.notifications.selectors.inbox_guard import open_guard_alerts
from tests.pg.conftest import sign_up
from tests.pg.test_cabinet_flows import _cabinet


def _figures(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    back: int,
    spend: int,
    leads: int,
    now: datetime,
    impressions: int = 4_000,
    link_clicks: int = 40,
) -> None:
    """One day of s_1, ``back`` days ago in the account's clock; today is 0."""
    day = now.astimezone(account.tzinfo()).date() - timedelta(days=back)
    db.execute(
        MetricsDaily.__table__.delete().where(
            MetricsDaily.owner_id == owner.id,
            MetricsDaily.level == "adset",
            MetricsDaily.adset_external_id == "s_1",
            MetricsDaily.date == day,
        )
    )
    db.add(
        MetricsDaily(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id="s_1",
            ad_account_id=account.id,
            level="adset",
            campaign_external_id="c_1",
            adset_external_id="s_1",
            date=day,
            spend_minor=spend,
            currency="USD",
            impressions=impressions,
            clicks=link_clicks + 10,
            inline_link_clicks=link_clicks,
            leads_reported=leads,
            results_reported=leads,
            synced_at=now,
        )
    )
    db.commit()


def _running(
    client: TestClient, db: Session, *, launched_here: bool = True
) -> tuple[User, AdAccount, datetime]:
    """A lead group ten days old whose usual lead costs $2 (200 minor)."""
    from tests.pg.test_ads_manage import _mirror

    sign_up(client)
    owner = db.scalar(select(User))
    assert owner is not None
    now = utcnow()
    start_trial(db, user=owner, now=now)
    account, page = _cabinet(db, owner)
    account.is_active = account.is_current = True
    page.is_current = page.is_active = True
    account.synced_at = now
    db.commit()
    _mirror(db, owner, account.id)
    group = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert group is not None
    group.daily_budget_minor = 5_000
    group.optimization_goal_raw = "LEAD_GENERATION"
    group.delivery = "active"
    group.start_time = now - timedelta(days=10)
    if launched_here:
        db.add(
            CampaignLaunch(
                owner_id=owner.id,
                ad_account_id=account.id,
                page_id=page.id,
                provider=PROVIDER,
                status="created",
                created_refs={"campaign": "c_1", "adset": ["s_1"], "ad": ["a_1"]},
                delivery_started_at=now - timedelta(days=10),
            )
        )
    db.commit()
    for back in range(1, 10):
        _figures(
            db, owner=owner, account=account, back=back, spend=1_000, leads=5, now=now
        )
    return owner, account, now


def _today(
    db: Session, owner: User, account: AdAccount, now: datetime, **figures: int
) -> None:
    _figures(db, owner=owner, account=account, back=0, now=now, **figures)  # type: ignore[arg-type]


def _rows(db: Session) -> list[GuardAlert]:
    db.expire_all()
    return list(db.scalars(select(GuardAlert).order_by(GuardAlert.created_at)))


def _land(db: Session, *, status: str = ActionStatus.APPLIED, **result: str) -> None:
    """Every change still on its way, answered by the provider."""
    from app.modules.agent.services.guard_outcome import note_change_settled

    pending = list(
        db.scalars(select(ActionLog).where(ActionLog.status == ActionStatus.PENDING))
    )
    for log in pending:
        log.status = status
        if status == ActionStatus.FAILED:
            log.error_code = result.get("code", "provider_error")
            log.result_payload = {"user_message": result.get("message", "")}
        else:
            log.applied_at = utcnow()
    db.commit()
    for log in pending:
        note_change_settled(db, log_id=str(log.id), now=utcnow())


def _pauses(db: Session) -> list[ActionLog]:
    return list(
        db.scalars(select(ActionLog).where(ActionLog.action == str(ActionType.PAUSE)))
    )


def test_a_usual_day_says_nothing(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=600, leads=3)

    assert run_guard(db, owner=owner, now=now) == 0
    assert _rows(db) == []


def test_five_is_said_once_and_ten_stops(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)

    # Three and four usual prices: nothing is said.
    for spend in (1_920, 2_460):
        _today(db, owner, account, now, spend=spend, leads=3)
        assert run_guard(db, owner=owner, now=now) == 0
    assert _rows(db) == []

    _today(db, owner, account, now, spend=3_060, leads=3)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action, row.step, row.times) == ("price", "warn", 5, 510)
    assert row.advice == "pause"
    assert row.figures["usual_cost_minor"] == 200
    assert row.figures["usual_source"] == "own"
    assert _pauses(db) == []

    # The next half hours at the same step: nothing new.
    _today(db, owner, account, now, spend=3_300, leads=3)
    assert run_guard(db, owner=owner, now=now) == 0
    assert _rows(db)[0].step == 5

    _today(db, owner, account, now, spend=6_060, leads=3)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.action, row.step) == ("stop", 10)
    (log,) = _pauses(db)
    # The campaign's one group: the campaign's switch is what stops it.
    assert (log.target_level, log.target_external_id) == ("campaign", "c_1")
    assert row.figures["sole_group"] is True
    assert log.status == ActionStatus.PENDING
    assert log.request_payload[GUARD_STOP_MARK]["kind"] == "price"
    assert row.action_log_id == log.id
    assert row.baseline["spend_minor"] == 6_060

    # While the stop is on its way nothing is asked twice, and it stays said.
    assert run_guard(db, owner=owner, now=now) == 0
    assert len(_pauses(db)) == 1
    assert _rows(db)[0].closed_at is None


def test_a_rise_that_eases_closes_and_a_new_one_is_a_new_row(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=3_060, leads=3)
    run_guard(db, owner=owner, now=now)

    _today(db, owner, account, now, spend=700, leads=4)
    assert run_guard(db, owner=owner, now=now) == 0
    (row,) = _rows(db)
    assert row.closed_at is not None

    _today(db, owner, account, now, spend=5_100, leads=5)
    assert run_guard(db, owner=owner, now=now) == 1
    assert [r.closed_at is None for r in _rows(db)] == [False, True]


def test_nothing_back_for_five_usual_prices_is_stopped(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=999, leads=0)
    assert run_guard(db, owner=owner, now=now) == 0

    _today(db, owner, account, now, spend=1_000, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action) == ("fruitless", "stop")
    assert len(_pauses(db)) == 1


def test_a_group_built_elsewhere_is_only_warned(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db, launched_here=False)
    _today(db, owner, account, now, spend=3_600, leads=3)

    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action, row.step, row.advice) == ("price", "warn", 5, "pause")
    assert _pauses(db) == []


def test_an_owner_with_the_agent_off_is_only_warned(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=1_000, leads=0)

    assert run_guard(db, owner=owner, now=now, may_stop=False) == 1
    (row,) = _rows(db)
    assert (row.action, row.advice) == ("warn", "pause")
    assert _pauses(db) == []


def test_the_first_day_is_not_judged(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    launch = db.scalar(select(CampaignLaunch))
    assert launch is not None
    launch.delivery_started_at = now - timedelta(hours=23)
    db.commit()
    _today(db, owner, account, now, spend=5_000, leads=0)

    assert run_guard(db, owner=owner, now=now) == 0


def test_stale_figures_are_not_judged(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=5_000, leads=0)
    account.synced_at = now - timedelta(hours=2)
    db.commit()

    assert run_guard(db, owner=owner, now=now) == 0


def test_switched_back_on_the_group_is_counted_from_the_stop(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=1_000, leads=0)
    run_guard(db, owner=owner, now=now)
    (log,) = _pauses(db)
    # The stop landed, and the owner switched the group back on.
    log.status = ActionStatus.APPLIED
    db.commit()

    _today(db, owner, account, now, spend=1_100, leads=0)
    assert run_guard(db, owner=owner, now=now) == 0
    (row,) = _rows(db)
    # Running again: the stop is no longer said, and $1 since is no verdict.
    assert row.closed_at is not None
    assert len(_pauses(db)) == 1

    _today(db, owner, account, now, spend=2_000, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    assert len(_pauses(db)) == 2


# -- the answers, the cabinet's line and the phone's message ------------------------------


def _warned(
    client: TestClient, db: Session, *, launched_here: bool = True
) -> tuple[User, AdAccount, datetime, GuardAlert]:
    """A price warning at 5.1 usual prices."""
    owner, account, now = _running(client, db, launched_here=launched_here)
    _today(db, owner, account, now, spend=3_060, leads=3)
    run_guard(db, owner=owner, now=now)
    (row,) = _rows(db)
    return owner, account, now, row


def test_leave_is_written_down_and_the_next_step_still_comes(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.agent.services.answer_guard import answer_guard

    # Built elsewhere: ten is a warning there, the next step after five.
    owner, account, now, row = _warned(client, db, launched_here=False)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="leave", now=now)
    db.commit()
    (row,) = _rows(db)
    assert (row.answer, row.closed_at) == ("leave", None)
    assert _pauses(db) == []
    # Answered: off the cabinet's list until the price goes a step further.
    assert open_guard_alerts(db, owner=owner) == []

    _today(db, owner, account, now, spend=3_300, leads=3)
    assert run_guard(db, owner=owner, now=now) == 0
    _today(db, owner, account, now, spend=6_060, leads=3)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.action, row.step, row.answer) == ("warn", 10, "")
    assert [found.id for found in open_guard_alerts(db, owner=owner)] == [row.id]


def test_pause_asks_the_provider_once_and_closes_the_finding(
    client: TestClient, db: Session, queued: list
) -> None:
    import pytest

    from app.modules.agent.exceptions import GuardAlertGone
    from app.modules.agent.services.answer_guard import answer_guard

    owner, _account, now, row = _warned(client, db)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    (row,) = _rows(db)
    # Open while the stop is on its way: a refusal must bring the buttons back.
    assert row.answer == "pause" and row.closed_at is None
    assert row.answer_log_id == _pauses(db)[0].id
    assert row.baseline["spend_minor"] == 3_060
    assert len(_pauses(db)) == 1
    with pytest.raises(GuardAlertGone):
        answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.rollback()

    _land(db)
    (row,) = _rows(db)
    assert (row.result, row.closed_at is not None) == ("applied", True)


def test_the_budget_goes_down_a_fifth(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.agent.services.answer_guard import answer_guard

    owner, _account, now, row = _warned(client, db)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="budget_down", now=now)
    db.commit()
    (log,) = db.scalars(
        select(ActionLog).where(ActionLog.action != str(ActionType.PAUSE))
    ).all()
    assert "budget" in str(log.action).lower()
    assert 4_000 in (log.request_payload or {}).values()
    assert _rows(db)[0].closed_at is None


def test_an_answer_the_finding_does_not_offer_is_refused(
    client: TestClient, db: Session, queued: list
) -> None:
    import pytest

    from app.modules.agent.exceptions import GuardAnswerUnknown
    from app.modules.agent.services.answer_guard import answer_guard

    owner, _account, now, row = _warned(client, db)
    with pytest.raises(GuardAnswerUnknown):
        answer_guard(db, user=owner, alert_id=str(row.id), answer="resume", now=now)


def test_the_phone_hears_of_a_group_once_a_day_and_of_a_stop_always(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    from app.common.config import settings
    from app.modules.notifications.models import TelegramChat, TelegramNotice
    from app.modules.notifications.services.announce_guard import announce_guard
    from tests.pg.test_office_telegram import FakeBot

    monkeypatch.setattr(settings, "site_url", "https://targetolog.test")
    owner, account, now, row = _warned(client, db)
    db.add(
        TelegramChat(owner_id=owner.id, chat_id="700", is_active=True, linked_at=now)
    )
    db.commit()
    phone = FakeBot()

    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 0
    (text,) = phone.texts()
    assert "Narx 5,1 baravar qimmatlashdi" in text or "выросла в 5,1 раза" in text
    (row,) = _rows(db)
    assert row.said_step == 5 and row.telegram_sent_at is not None

    # Ten stops it the same day, and a stop is always said - once it landed.
    _today(db, owner, account, now, spend=6_060, leads=3)
    run_guard(db, owner=owner, now=now)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 0
    _land(db)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1
    assert len(phone.texts()) == 2
    subjects = set(db.scalars(select(TelegramNotice.subject)))
    assert subjects == {f"guard:{row.id}:5", f"guard:{row.id}:10:stop"}


def test_a_second_warning_the_same_day_is_not_sent(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    from app.modules.notifications.services.announce_guard import announce_guard

    # Built elsewhere: ten is only a warning.
    owner, account, now, _row = _warned(client, db, launched_here=False)
    phone = _linked_phone(db, owner, now, monkeypatch)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1

    # Ten the same day: written down for the cabinet, not sent - a group
    # is warned about once a day.
    _today(db, owner, account, now, spend=6_060, leads=3)
    run_guard(db, owner=owner, now=now)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 0
    (row,) = _rows(db)
    assert (row.action, row.step, row.said_step) == ("warn", 10, 10)
    assert len(phone.texts()) == 1


def test_a_warning_waits_for_the_morning_and_a_stop_does_not(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.notifications.models import TelegramChat
    from app.modules.notifications.services.announce_guard import announce_guard
    from tests.pg.test_office_telegram import FakeBot

    owner, account, now, _row = _warned(client, db)
    db.add(
        TelegramChat(owner_id=owner.id, chat_id="700", is_active=True, linked_at=now)
    )
    db.commit()
    phone = FakeBot()
    asleep = {str(owner.id)}

    assert announce_guard(db, client=phone, now=now, asleep=asleep) == 0
    _today(db, owner, account, now, spend=6_060, leads=3)
    run_guard(db, owner=owner, now=now)
    _land(db)
    assert announce_guard(db, client=phone, now=now, asleep=asleep) == 1
    (text,) = phone.texts()
    assert "To'xtatdim" in text or "Остановил" in text


def test_the_cabinet_draws_the_finding_with_its_advised_answer(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.notifications.selectors.inbox_guard import guard_item

    _owner, _account, _now, row = _warned(client, db)
    item = guard_item(row)
    assert item.key == f"guard:{row.id}:5"
    assert (item.kind, item.level) == ("price", "urgent")
    assert [action.href.rsplit("/", 1)[1] for action in item.actions] == [
        "pause", "budget_down", "leave",
    ]  # fmt: skip
    assert sum(action.advised for action in item.actions) == 1


def test_a_small_budget_is_stopped_for_its_dry_days_together(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    # A result five days ago at the usual price, then $3.30 a day for nothing.
    for back in (1, 2, 3):
        _figures(
            db, owner=owner, account=account, back=back, spend=330, leads=0, now=now
        )
    _today(db, owner, account, now, spend=40, leads=0)

    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action) == ("fruitless", "stop")
    assert row.figures["dry_days"] == 4
    assert row.figures["dry_spend_minor"] == 1_030


def test_a_finding_names_its_page_and_campaign(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.ads.models import Campaign
    from app.modules.integrations.models import PageAccount

    owner, account, now = _running(client, db)
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == owner.id))
    group = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert page is not None and group is not None
    page.name = "Gul do'koni"
    group.promoted_object_raw = {"page_id": page.external_id}
    campaign = db.scalar(select(Campaign).where(Campaign.external_id == "c_1"))
    assert campaign is not None
    db.commit()

    _today(db, owner, account, now, spend=3_060, leads=3)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert row.figures["page_name"] == "Gul do'koni"
    assert row.figures["campaign_name"] == (campaign.name or "c_1")
    assert row.figures["group_name"] == row.name


def test_old_open_findings_get_their_page_and_campaign_named(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.integrations.models import PageAccount
    from tools.guard_place_backfill import fill

    owner, account, now = _running(client, db)
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == owner.id))
    group = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert page is not None and group is not None
    page.name = "Gul do'koni"
    group.promoted_object_raw = {"page_id": page.external_id}
    db.commit()
    _today(db, owner, account, now, spend=3_060, leads=3)
    run_guard(db, owner=owner, now=now)
    (row,) = _rows(db)
    # As a finding written before the names were kept.
    old = dict(row.figures)
    old.pop("page_name")
    old.pop("campaign_name")
    row.figures, row.said_step = old, row.step
    db.commit()

    assert fill(db) == (1, 1)
    db.commit()
    (row,) = _rows(db)
    assert row.figures["page_name"] == "Gul do'koni"
    assert row.figures["campaign_name"]
    assert row.said_step == row.step  # nothing is told again
    assert fill(db) == (1, 0)


def test_a_sent_message_is_rewritten_in_place_with_its_page(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    from app.common.config import settings
    from app.modules.notifications.models import TelegramChat
    from app.modules.notifications.services.announce_guard import announce_guard
    from tests.pg.test_office_telegram import FakeBot
    from tools.guard_place_telegram import _edit, sent_messages

    monkeypatch.setattr(settings, "site_url", "https://targetolog.test")
    # Built elsewhere, so ten is a warning too.
    owner, account, now, row = _warned(client, db, launched_here=False)
    db.add(
        TelegramChat(owner_id=owner.id, chat_id="700", is_active=True, linked_at=now)
    )
    db.commit()
    phone = FakeBot()
    # Step 5 then step 10 sent, both before the names were kept.
    for day, spend in enumerate((3_060, 6_060)):
        _today(db, owner, account, now, spend=spend, leads=3)
        run_guard(db, owner=owner, now=now)
        (row,) = _rows(db)
        row.figures = {
            k: v
            for k, v in row.figures.items()
            if k not in ("page_name", "campaign_name")
        }
        db.commit()
        # A day apart: a group is warned about once a day.
        later = now + timedelta(days=day)
        announce_guard(db, client=phone, now=later, asleep=set())
    assert len(phone.texts()) == 2
    sent_ids = [c[1] for c in phone.calls if c[0] == "send_message"]
    assert sent_messages(db) == []  # nothing named yet: nothing to rewrite

    (row,) = _rows(db)
    row.figures = {**row.figures, "page_name": "Gul", "campaign_name": "Kuz"}
    db.commit()
    ((found, notice, chat),) = sent_messages(db)
    assert notice.subject == f"guard:{row.id}:10"  # the present step only
    assert _edit(phone, row=found, notice=notice, chat=chat)

    (edit,) = [fields for name, fields in phone.calls if name == "edit_message_text"]
    assert edit["chat_id"] == "700"
    assert edit["message_id"] == notice.message_id == 102
    assert "Sahifa: Gul" in edit["text"] or "Страница: Gul" in edit["text"]
    assert edit["buttons"]  # the answers stay under it
    assert len(phone.texts()) == 2  # no new message
    assert len(sent_ids) == 2


def _linked_phone(db: Session, owner: User, now: datetime, monkeypatch):
    from app.common.config import settings
    from app.modules.notifications.models import TelegramChat
    from tests.pg.test_office_telegram import FakeBot

    monkeypatch.setattr(settings, "site_url", "https://targetolog.test")
    db.add(
        TelegramChat(owner_id=owner.id, chat_id="700", is_active=True, linked_at=now)
    )
    db.commit()
    return FakeBot()


def test_a_group_missing_from_one_reading_is_not_said_again(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    from app.modules.notifications.services.announce_guard import announce_guard

    owner, account, now, _row = _warned(client, db)
    phone = _linked_phone(db, owner, now, monkeypatch)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1

    # One sync reads the group as «with issues», the next as running again.
    group = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert group is not None
    group.delivery = "rejected"
    db.commit()
    run_guard(db, owner=owner, now=now)
    group.delivery = "active"
    db.commit()
    run_guard(db, owner=owner, now=now)

    assert announce_guard(db, client=phone, now=now, asleep=set()) == 0
    assert len(phone.texts()) == 1
    old, new = _rows(db)
    assert old.closed_at is not None and new.closed_at is None
    assert (new.step, new.said_step) == (5, 5)

    # A stop is said at once, once it landed.
    _today(db, owner, account, now, spend=6_060, leads=3)
    run_guard(db, owner=owner, now=now)
    _land(db)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1


def test_a_price_hovering_at_its_bar_is_said_once_a_day(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    from app.modules.agent.services.answer_guard import answer_guard
    from app.modules.notifications.services.announce_guard import announce_guard

    owner, account, now, row = _warned(client, db)  # 5.1 usual prices
    phone = _linked_phone(db, owner, now, monkeypatch)
    announce_guard(db, client=phone, now=now, asleep=set())
    answer_guard(db, user=owner, alert_id=str(row.id), answer="leave", now=now)
    db.commit()

    # Eases under two, back at five, eases, back at five.
    for spend, leads in [(2_000, 6), (6_000, 6), (4_100, 12), (12_000, 12)]:
        _today(db, owner, account, now, spend=spend, leads=leads)
        run_guard(db, owner=owner, now=now)
        assert announce_guard(db, client=phone, now=now, asleep=set()) == 0

    assert len(phone.texts()) == 1
    rows = [row for row in _rows(db) if row.kind == "price"]
    assert len(rows) == 3
    # Still answered: it does not come back to the cabinet's list either.
    assert rows[-1].answer == "leave"
    assert [r for r in open_guard_alerts(db, owner=owner) if r.kind == "price"] == []


def test_a_warning_still_true_tomorrow_is_said_again(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    from app.modules.notifications.services.announce_guard import announce_guard

    owner, _account, now, row = _warned(client, db)
    phone = _linked_phone(db, owner, now, monkeypatch)
    announce_guard(db, client=phone, now=now, asleep=set())
    # Raised yesterday and closed: today's rise is today's news.
    row.created_at = row.telegram_sent_at = now - timedelta(days=1)
    row.closed_at = now - timedelta(hours=1)
    db.commit()

    run_guard(db, owner=owner, now=now)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1


def test_yesterdays_price_is_not_raised_a_step_by_this_mornings_first_lead(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    """The Elegant Style case of 2026-11-17: a rise last night, one lead at
    six usual prices this morning, said as the rise going on."""
    from app.modules.notifications.services.announce_guard import announce_guard

    owner, account, now, row = _warned(client, db)
    phone = _linked_phone(db, owner, now, monkeypatch)
    announce_guard(db, client=phone, now=now, asleep=set())
    yesterday = now.astimezone(account.tzinfo()).date() - timedelta(days=1)
    row.figures = {**row.figures, "day": yesterday.isoformat()}
    row.created_at = row.telegram_sent_at = now - timedelta(days=1)
    db.commit()

    # This morning: one lead at six usual prices.
    _today(db, owner, account, now, spend=1_200, leads=1)
    run_guard(db, owner=owner, now=now)

    (old,) = _rows(db)
    assert old.closed_at is not None and old.step == 5
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 0
    assert len(phone.texts()) == 1


# -- a new group: held against itself, never against another group -------------------------


def _new_group(
    client: TestClient, db: Session, *, hours_on: int, launched_here: bool = True
) -> tuple[User, AdAccount, datetime]:
    """s_1 switched on ``hours_on`` hours ago with a day's budget of $50 and
    no day of figures yet."""
    owner, account, now = _running(client, db, launched_here=launched_here)
    db.execute(MetricsDaily.__table__.delete().where(MetricsDaily.owner_id == owner.id))
    started = now - timedelta(hours=hours_on)
    group = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert group is not None
    group.start_time = started
    launch = db.scalar(select(CampaignLaunch))
    if launch is not None:
        launch.delivery_started_at = started
    db.commit()
    return owner, account, now


def _later(db: Session, account: AdAccount, now: datetime, hours: int) -> datetime:
    """The clock moved on, the account read again."""
    later = now + timedelta(hours=hours)
    account.synced_at = later
    db.commit()
    return later


def test_another_group_s_price_is_never_a_new_group_s(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.agent.models import AdSetDiagnosis

    owner, account, now = _new_group(client, db, hours_on=30)
    today = now.astimezone(account.tzinfo()).date()
    # Last night read the account's other lead groups at $1 a lead.
    db.add(
        AdSetDiagnosis(
            owner_id=owner.id,
            provider=PROVIDER,
            adset_external_id="s_1",
            evidence={"currency": "USD", "account_cost_minor": 100, "outcome": "lead"},
            since=today - timedelta(days=7),
            until=today - timedelta(days=1),
            diagnosed_at=now,
        )
    )
    db.commit()
    # Thirty of those prices gone, and under this group's own day's budget.
    _today(db, owner, account, now, spend=3_000, leads=0)
    assert run_guard(db, owner=owner, now=now) == 0
    assert _rows(db) == [] and _pauses(db) == []


def test_a_day_s_budget_with_nothing_back_warns_a_new_group(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.agent.guard_copy import guard_body

    owner, account, now = _new_group(client, db, hours_on=30)
    # The first day's money counts toward the day's budget.
    _figures(db, owner=owner, account=account, back=1, spend=3_000, leads=0, now=now)
    _today(db, owner, account, now, spend=1_999, leads=0)
    assert run_guard(db, owner=owner, now=now) == 0

    _today(db, owner, account, now, spend=2_000, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action, row.step, row.advice) == (
        "fruitless", "warn", 1, "pause",
    )  # fmt: skip
    assert row.figures["usual_cost_minor"] is None
    assert row.figures["day_budget_minor"] == 5_000
    with override("uz"):
        body = guard_body(row)
    assert "Kunlik byudjet: $50" in body
    assert "3 kun o'tib ham natija bo'lmasa" in body
    assert _pauses(db) == []
    # Said once: the same finding half an hour later changes nothing.
    assert run_guard(db, owner=owner, now=now) == 0


def test_three_days_on_with_no_result_ever_is_stopped(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.agent.guard_copy import guard_body, guard_title

    owner, account, now = _new_group(client, db, hours_on=48)
    _today(db, owner, account, now, spend=5_000, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    assert _pauses(db) == []

    now = _later(db, account, now, 25)
    _today(db, owner, account, now, spend=5_000, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action, row.step) == ("fruitless", "stop", 2)
    (log,) = _pauses(db)
    assert log.request_payload[GUARD_STOP_MARK]["kind"] == "fruitless"
    with override("uz"):
        assert "To'xtatdim" in guard_title(row)
        assert "yoqilganiga 3 kun bo'ldi" in guard_body(row)


def test_leave_holds_the_stop_back_for_three_days(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.agent.services.answer_guard import answer_guard

    owner, account, now = _new_group(client, db, hours_on=48)
    _today(db, owner, account, now, spend=5_000, leads=0)
    run_guard(db, owner=owner, now=now)
    (row,) = _rows(db)
    answered = now
    answer_guard(db, user=owner, alert_id=str(row.id), answer="leave", now=answered)
    db.commit()

    # Three days on: it would be stopped, and the owner said to leave it.
    now = _later(db, account, now, 25)
    _today(db, owner, account, now, spend=5_000, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.action, row.step, row.answer) == ("warn", 2, "leave")
    # Nothing new to say or to show: the owner has answered it.
    assert row.said_step == 2 and open_guard_alerts(db, owner=owner) == []
    assert _pauses(db) == []
    assert run_guard(db, owner=owner, now=now) == 0

    # Three days after the answer the stop is the guard's again.
    now = _later(db, account, answered, 73)
    _today(db, owner, account, now, spend=5_000, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.action, row.step) == ("stop", 2)
    # The stop is still to be said, though its step was passed in silence.
    assert row.said_step < row.step
    assert len(_pauses(db)) == 1


def test_a_new_group_built_elsewhere_is_never_stopped(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _new_group(client, db, hours_on=100, launched_here=False)
    _today(db, owner, account, now, spend=5_000, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.action, row.step) == ("warn", 1)
    assert _pauses(db) == []


def test_a_new_group_is_held_against_its_own_first_results(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.agent.guard_copy import guard_body

    owner, account, now = _new_group(client, db, hours_on=100)
    # Three leads at $2 on its second day: the price of its own start.
    _figures(db, owner=owner, account=account, back=2, spend=600, leads=3, now=now)
    # Ten of those prices for a lead today: said, never stopped for.
    _today(db, owner, account, now, spend=6_000, leads=3)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action, row.step) == ("price", "warn", 10)
    assert row.figures["usual_source"] == "start"
    assert row.figures["usual_cost_minor"] == 200
    with override("uz"):
        body = guard_body(row)
    assert "Shu reklamaning o'zida" in body and "o'zim to'xtataman" not in body
    assert _pauses(db) == []


def test_a_new_group_is_stopped_for_three_of_its_own_prices_with_nothing_back(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _new_group(client, db, hours_on=100)
    _figures(db, owner=owner, account=account, back=2, spend=600, leads=3, now=now)
    # The dry day after is judged, and is not part of the price it is held to.
    _figures(db, owner=owner, account=account, back=1, spend=400, leads=0, now=now)
    _today(db, owner, account, now, spend=199, leads=0)
    assert run_guard(db, owner=owner, now=now) == 0

    _today(db, owner, account, now, spend=200, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action) == ("fruitless", "stop")
    assert row.figures["usual_source"] == "start"
    assert len(_pauses(db)) == 1
