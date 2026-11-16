"""The half-hourly guard against PostgreSQL: a price said at three and four
usual prices and stopped at five, money gone with nothing back stopped,
nothing said twice, and a group switched back on counted from there."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
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


def test_three_then_four_are_said_once_each_and_five_stops(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)

    _today(db, owner, account, now, spend=640, leads=1)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action, row.step, row.times) == ("price", "warn", 3, 320)
    assert row.figures["usual_cost_minor"] == 200
    assert row.figures["usual_source"] == "own"

    # The next half hours at the same step: nothing new.
    _today(db, owner, account, now, spend=700, leads=1)
    assert run_guard(db, owner=owner, now=now) == 0
    assert _rows(db)[0].step == 3

    _today(db, owner, account, now, spend=820, leads=1)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.action, row.step, row.advice) == ("warn", 4, "pause")
    assert _pauses(db) == []

    _today(db, owner, account, now, spend=1_010, leads=1)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.action, row.step) == ("stop", 5)
    (log,) = _pauses(db)
    assert log.target_external_id == "s_1"
    assert log.status == ActionStatus.PENDING
    assert log.request_payload[GUARD_STOP_MARK]["kind"] == "price"
    assert row.action_log_id == log.id
    assert row.baseline["spend_minor"] == 1_010

    # While the stop is on its way nothing is asked twice.
    assert run_guard(db, owner=owner, now=now) == 0
    assert len(_pauses(db)) == 1


def test_a_rise_that_eases_closes_and_a_new_one_is_a_new_row(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=640, leads=1)
    run_guard(db, owner=owner, now=now)

    _today(db, owner, account, now, spend=700, leads=4)
    assert run_guard(db, owner=owner, now=now) == 0
    (row,) = _rows(db)
    assert row.closed_at is not None

    _today(db, owner, account, now, spend=3_300, leads=5)
    assert run_guard(db, owner=owner, now=now) == 1
    assert [r.closed_at is None for r in _rows(db)] == [False, True]


def test_nothing_back_for_three_usual_prices_is_stopped(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=599, leads=0)
    assert run_guard(db, owner=owner, now=now) == 0

    _today(db, owner, account, now, spend=600, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action) == ("fruitless", "stop")
    assert len(_pauses(db)) == 1


def test_a_group_built_elsewhere_is_only_warned(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db, launched_here=False)
    _today(db, owner, account, now, spend=1_200, leads=1)

    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action, row.step, row.advice) == ("price", "warn", 5, "pause")
    assert _pauses(db) == []


def test_an_owner_with_the_agent_off_is_only_warned(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=600, leads=0)

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
    _today(db, owner, account, now, spend=600, leads=0)
    run_guard(db, owner=owner, now=now)
    (log,) = _pauses(db)
    # The stop landed, and the owner switched the group back on.
    log.status = ActionStatus.APPLIED
    db.commit()

    _today(db, owner, account, now, spend=700, leads=0)
    assert run_guard(db, owner=owner, now=now) == 0
    (row,) = _rows(db)
    # Running again: the stop is no longer said, and $1 since is no verdict.
    assert row.closed_at is not None
    assert len(_pauses(db)) == 1

    _today(db, owner, account, now, spend=1_200, leads=0)
    assert run_guard(db, owner=owner, now=now) == 1
    assert len(_pauses(db)) == 2


# -- the answers, the cabinet's line and the phone's message ------------------------------


def _warned(
    client: TestClient, db: Session
) -> tuple[User, AdAccount, datetime, GuardAlert]:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=640, leads=1)
    run_guard(db, owner=owner, now=now)
    (row,) = _rows(db)
    return owner, account, now, row


def test_leave_is_written_down_and_the_next_step_still_comes(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.agent.services.answer_guard import answer_guard

    owner, account, now, row = _warned(client, db)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="leave", now=now)
    db.commit()
    (row,) = _rows(db)
    assert (row.answer, row.closed_at) == ("leave", None)
    assert _pauses(db) == []
    # Answered: off the cabinet's list until the price goes a step further.
    assert open_guard_alerts(db, owner=owner) == []

    _today(db, owner, account, now, spend=700, leads=1)
    assert run_guard(db, owner=owner, now=now) == 0
    _today(db, owner, account, now, spend=820, leads=1)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.step, row.answer) == (4, "")
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
    assert row.answer == "pause" and row.closed_at is not None
    assert row.baseline["spend_minor"] == 640
    assert len(_pauses(db)) == 1
    with pytest.raises(GuardAlertGone):
        answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)


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


def test_the_phone_is_told_each_step_once(
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
    assert "Narx 3,2 baravar qimmatlashdi" in text or "выросла в 3,2 раза" in text
    (row,) = _rows(db)
    assert row.said_step == 3 and row.telegram_sent_at is not None

    _today(db, owner, account, now, spend=820, leads=1)
    run_guard(db, owner=owner, now=now)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1
    assert len(phone.texts()) == 2
    subjects = set(db.scalars(select(TelegramNotice.subject)))
    assert subjects == {f"guard:{row.id}:3", f"guard:{row.id}:4"}


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
    _today(db, owner, account, now, spend=1_010, leads=1)
    run_guard(db, owner=owner, now=now)
    assert announce_guard(db, client=phone, now=now, asleep=asleep) == 1
    (text,) = phone.texts()
    assert "To'xtatdim" in text or "Остановил" in text


def test_the_cabinet_draws_the_finding_with_its_advised_answer(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.notifications.selectors.inbox_guard import guard_item

    _owner, _account, _now, row = _warned(client, db)
    item = guard_item(row)
    assert item.key == f"guard:{row.id}:3"
    assert (item.kind, item.level) == ("price", "urgent")
    assert [action.href.rsplit("/", 1)[1] for action in item.actions] == [
        "pause", "budget_down", "leave",
    ]  # fmt: skip
    assert sum(action.advised for action in item.actions) == 1


def test_a_small_budget_is_stopped_for_its_dry_days_together(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    # A result five days ago at the usual price, then $2.50 a day for nothing.
    for back in (1, 2, 3):
        _figures(
            db, owner=owner, account=account, back=back, spend=250, leads=0, now=now
        )
    _today(db, owner, account, now, spend=40, leads=0)

    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert (row.kind, row.action) == ("fruitless", "stop")
    assert row.figures["dry_days"] == 4
    assert row.figures["dry_spend_minor"] == 790


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

    _today(db, owner, account, now, spend=640, leads=1)
    assert run_guard(db, owner=owner, now=now) == 1
    (row,) = _rows(db)
    assert row.figures["page_name"] == "Gul do'koni"
    assert row.figures["campaign_name"] == (campaign.name or "c_1")
    assert row.figures["group_name"] == row.name
