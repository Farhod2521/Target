"""What the assistant could not see before 2026-11-19 and now reads: the
guard's warnings and stops, the bound card and autopay, the CRM's managers,
the invite link and wallet, an unfinished setup, and the nightly check
against Ads Manager."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.common.i18n import override
from app.modules.accounts.models import User
from app.modules.agent.models import GuardAlert
from app.modules.assistant.selectors.crm_outcomes import crm_outcomes
from app.modules.assistant.selectors.guard import guard_alerts
from app.modules.assistant.selectors.health import account_health
from app.modules.assistant.selectors.referrals import referrals_text
from app.modules.billing.selectors import live_subscription
from app.modules.chat.selectors.lookups import answer_lookup
from app.modules.chat.selectors.scope import asked_scopes
from app.modules.metrics.models import MetricsCheck
from core.chat import lookup_arguments as args
from tests.pg.conftest import sign_up
from tests.pg.test_assistant import _with_plan
from tests.pg.test_chat import _account, _mirror
from tests.pg.test_crm_quality_counts import _board


def _scope(db: Session, owner: User):  # type: ignore[no-untyped-def]
    return asked_scopes(db, owner=owner)[0]


# -- the guard ---------------------------------------------------------------


def _alert(db: Session, owner: User, account, **fields) -> GuardAlert:  # type: ignore[no-untyped-def]
    row = GuardAlert(
        owner_id=owner.id,
        provider="meta",
        ad_account_id=account.id,
        level="adset",
        external_id=fields.pop("external_id", "as_1"),
        adset_external_id="as_1",
        campaign_external_id="c_1",
        name="Toshkent ayollar",
        currency="USD",
        result_kind="lead",
        **fields,
    )
    db.add(row)
    db.commit()
    return row


def test_a_stop_is_told_in_the_owners_words_with_when(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)
    now = utcnow()
    _alert(
        db,
        owner,
        account,
        kind="price",
        action="stop",
        times=1000,
        figures={
            "spend_minor": 3000,
            "results": 1,
            "usual_cost_minor": 300,
            "campaign_name": "Bahor aksiyasi",
            "sole_group": False,
            "ours": True,
        },
        telegram_sent_at=now,
    )
    _alert(
        db,
        owner,
        account,
        external_id="as_2",
        kind="fruitless",
        action="warn",
        figures={"spend_minor": 900, "usual_cost_minor": 300, "ours": True},
        answer="leave",
        answered_at=now,
    )
    with override("uz"):
        text = guard_alerts(db, owner=owner, scope=_scope(db, owner), days=7, now=now)
    assert "STOPPED · Kampaniya: «Bahor aksiyasi» · Guruh: «Toshkent ayollar»" in text
    assert "title: To'xtatdim: narx 10 baravar qimmat" in text
    assert "Bugun bitta lid: $30" in text and "Odatda: $3" in text
    assert "cabinet list and Telegram" in text
    assert "the owner pressed «Hozircha tegmaslik»" in text


def test_no_finding_says_where_else_a_stop_came_from(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    owner, _account_row, _page = _account(db)
    text = guard_alerts(db, owner=owner, scope=_scope(db, owner), days=7, now=utcnow())
    assert "it warned about nothing and stopped nothing" in text
    assert "`recent_changes`" in text


# -- the card and autopay ----------------------------------------------------


@pytest.fixture
def autopay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "multicard_autopay_enabled", True)
    monkeypatch.setattr(settings, "multicard_card_callback_url", "https://x.test/cb")


def test_a_refused_automatic_charge_is_a_problem_with_its_fix(
    client: TestClient, db: Session, autopay: None
) -> None:
    from app.modules.autopay.models import SavedCard

    _headers, owner = _with_plan(client, db)
    subscription = live_subscription(db, owner=owner)
    assert subscription is not None
    now = utcnow()
    db.add(
        SavedCard(
            owner_id=owner.id,
            session_id="s-1",
            status="active",
            pan="860049******1234",
            ps="uzcard",
            autopay=True,
            consented_at=now,
            bound_at=now - timedelta(days=20),
            charge_term=subscription.expires_at,
            charge_attempts=1,
            last_charge_at=now - timedelta(hours=3),
            last_charge_outcome="declined",
            last_charge_error="Kartada mablag' yetarli emas.",
        )
    )
    db.commit()
    text = account_health(db, owner=owner, scope=_scope(db, owner), now=now)
    section = text.split("## Card and autopay")[1].split("##")[0]
    assert "card UZCARD 860049******1234 is bound" in section
    assert "autopay is on" in section
    assert "PROBLEM: the last automatic charge" in section
    assert "Kartada mablag' yetarli emas." in section
    assert "tried again 2 more time(s)" in section
    assert "«Obuna va to'lov» (/app/billing/)" in section


def test_no_card_says_nothing_renews_by_itself(
    client: TestClient, db: Session, autopay: None
) -> None:
    _headers, owner = _with_plan(client, db)
    text = account_health(db, owner=owner, scope=_scope(db, owner), now=utcnow())
    assert "no card is bound, so nothing renews by itself" in text


# -- an unfinished setup -----------------------------------------------------


def test_an_unfinished_setup_names_its_next_step(
    client: TestClient, db: Session
) -> None:
    _headers, owner = _with_plan(client, db)
    text = account_health(db, owner=owner, scope=_scope(db, owner), now=utcnow())
    section = text.split("## Setup")[1].split("##")[0]
    assert "setup on «Tayyorgarlik» (/app/start/) is not finished" in section
    assert "next step: «Meta akkauntini ulash»" in section


# -- the CRM's managers ------------------------------------------------------


def test_the_crm_says_who_works_the_leads(client: TestClient, db: Session) -> None:
    owner = _board(client, db)
    text = crm_outcomes(db, owner=owner, scope=_scope(db, owner), days=7, now=utcnow())
    team = text.split("## Who works these leads in the CRM")[1]
    assert "given 3" in team
    assert "Sotildi 1" in team


# -- the invite link and the wallet ------------------------------------------


def test_the_wallet_and_the_link_are_read_as_the_page_reads_them(
    client: TestClient, db: Session
) -> None:
    from app.modules.referrals.models import ReferralCode, ReferralReward

    _headers, owner = _with_plan(client, db)
    db.add(ReferralCode(owner_id=owner.id, code="ABCD2345"))
    db.add(
        ReferralReward(
            owner_id=owner.id,
            base_minor=99_000_000,
            currency="UZS",
            percent=20,
            amount_minor=19_800_000,
            earned_at=utcnow(),
        )
    )
    db.commit()
    text = referrals_text(db, owner=owner, now=utcnow())
    assert "/r/ABCD2345/" in text
    assert "nobody has signed up through their link yet" in text
    assert "available 198\xa0000 UZS" in text
    assert "taking money out to a card is closed for now" in text


# -- the nightly check against Ads Manager ------------------------------------


def test_a_day_apart_from_ads_manager_is_named_with_both_figures(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)
    day = date.today() - timedelta(days=2)
    db.add(
        MetricsCheck(
            owner_id=owner.id,
            ad_account_id=account.id,
            day=day,
            ours={"spend_minor": 1200, "impressions": 3400},
            theirs={"spend_minor": 1500, "impressions": 4100},
            differs=True,
            checked_at=utcnow(),
        )
    )
    db.commit()
    scope, counted = asked_scopes(db, owner=owner)
    text = answer_lookup(
        db,
        owner=owner,
        name="daily_figures",
        arguments=args.DailyFigures(days=7),
        scope=scope,
        now=utcnow(),
        counted=counted,
    )
    assert "## Checked against Ads Manager's own account total" in text
    assert "1 day(s) checked, 1 apart from Ads Manager" in text
    assert f"{day}: here spend $12, impressions 3400; Ads Manager spend $15" in text
    assert db.scalar(select(MetricsCheck.id)) is not None
