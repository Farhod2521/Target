"""Support tickets from a survey answer the office marked «yordam kerak»,
from a paid client with no ad in three days, and from a running campaign
that spent nothing in a day; against PostgreSQL."""

from datetime import timedelta

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Campaign, CampaignLaunch
from app.modules.backoffice.constants import Role
from app.modules.boards import triggers
from app.modules.boards.models import BoardCard
from app.modules.boards.schemas import HelpOptionsOut
from app.modules.integrations.models import AdAccount, PageAccount, ProviderConnection
from app.modules.metrics.models import MetricsDaily
from app.modules.surveys.models import Survey, SurveyQuestion, SurveyResponse
from app.worker import beat_schedule
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import _bought, _live
from tests.pg.test_cabinet_flows import _cabinet

URL = "/api/v2/office/surveys/questions"


def _question(db: Session, *, kind: str = "choice") -> SurveyQuestion:
    survey = Survey(name="Haftalik", title={"uz": "Qalaysiz?"})
    db.add(survey)
    db.flush()
    question = SurveyQuestion(
        survey_id=survey.id,
        position=1,
        kind=kind,
        text={"uz": "Sizga mutaxassis yordami kerakmi?"},
        options=[{"uz": "Ha, kerak"}, {"uz": "Yo'q"}, {"uz": "Keyinroq"}]
        if kind == "choice"
        else [],
    )
    db.add(question)
    db.commit()
    return question


def _answer(db: Session, owner: User, question: SurveyQuestion, *picks: int) -> None:
    db.add(
        SurveyResponse(
            owner_id=owner.id,
            survey_id=question.survey_id,
            language="uz",
            channel="web",
            answers=[
                {"question": str(question.id), "kind": "choice", "choices": list(picks)}
            ],
        )
    )
    db.commit()


def _ticket(db: Session, owner: User) -> BoardCard | None:
    db.expire_all()
    return db.scalar(
        select(BoardCard).where(
            BoardCard.board == "support", BoardCard.owner_id == owner.id
        )
    )


def test_the_superuser_marks_the_options_that_ask_for_a_specialist(
    client: TestClient, db: Session
) -> None:
    question = _question(db)
    boss = _staff(db, "boss@office.test", superuser=True)
    support = _staff(db, "support@office.test", Role.SUPPORT)
    path = f"{URL}/{question.id}/help-options"

    first = HelpOptionsOut.model_validate(client.get(path, headers=boss).json())
    assert [(o.text, o.help) for o in first.options] == [
        ("Ha, kerak", False),
        ("Yo'q", False),
        ("Keyinroq", False),
    ]
    saved = client.put(path, json={"options": [0, 0]}, headers=boss)
    assert saved.status_code == 200, saved.text
    assert [o.help for o in HelpOptionsOut.model_validate(saved.json()).options] == [
        True,
        False,
        False,
    ]
    assert client.put(path, json={"options": [7]}, headers=boss).status_code == 422
    assert client.get(path, headers=support).status_code == 404
    assert (
        client.get(
            f"{URL}/00000000-0000-0000-0000-000000000000/help-options", headers=boss
        ).status_code
        == 404
    )

    text = _question(db, kind="text")
    refused = client.put(
        f"{URL}/{text.id}/help-options", json={"options": [0]}, headers=boss
    )
    assert refused.status_code == 422


def test_choosing_a_marked_option_opens_a_ticket_once(
    client: TestClient, db: Session
) -> None:
    _live(db)
    question = _question(db)
    boss = _staff(db, "boss@office.test", superuser=True)
    client.put(f"{URL}/{question.id}/help-options", json={"options": [0]}, headers=boss)
    asks = _client(db, "asks@shop.test")
    fine = _client(db, "fine@shop.test")
    _answer(db, asks, question, 0)
    _answer(db, fine, question, 1)

    assert triggers.sweep_support(db, now=utcnow()) == 1
    ticket = _ticket(db, asks)
    assert ticket is not None and [r["code"] for r in ticket.reasons] == ["survey"]
    assert _ticket(db, fine) is None
    assert triggers.sweep_support(db, now=utcnow()) == 0


def test_an_answer_older_than_the_deploy_is_left_alone(db: Session) -> None:
    question = _question(db)
    old = _client(db, "old@shop.test")
    _answer(db, old, question, 0)
    _live(db, hours_ago=0)
    from app.modules.boards.models import SurveyHelpOption

    db.add(SurveyHelpOption(question_id=question.id, option_index=0))
    db.commit()

    assert triggers.sweep_support(db, now=utcnow()) == 0


def test_paid_three_days_ago_and_no_ad_switched_on_is_a_ticket(db: Session) -> None:
    _live(db, hours_ago=24 * 5)
    idle = _client(db, "idle@shop.test")
    busy = _client(db, "busy@shop.test")
    recent = _client(db, "recent@shop.test")
    _bought(db, idle, minutes_ago=60 * 24 * 3 + 5, setup_done=True)
    _bought(db, busy, minutes_ago=60 * 24 * 4, setup_done=True)
    _bought(db, recent, minutes_ago=60 * 24 * 2, setup_done=True)
    account, page = _cabinet(db, busy)
    db.add(
        CampaignLaunch(
            owner_id=busy.id,
            ad_account_id=account.id,
            page_id=page.id,
            provider=PROVIDER,
            status="created",
        )
    )
    db.commit()

    assert triggers.sweep_idle(db, now=utcnow()) == 1
    ticket = _ticket(db, idle)
    assert ticket is not None and [r["code"] for r in ticket.reasons] == ["idle"]
    assert _ticket(db, busy) is None and _ticket(db, recent) is None
    assert triggers.sweep_idle(db, now=utcnow()) == 0


def _own_cabinet(db: Session, owner: User) -> tuple[AdAccount, PageAccount]:
    """A cabinet of its own per client, so several can sit side by side."""
    tag = str(owner.id)[:8]
    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id=f"fb-{tag}",
        token_encrypted=b"x",
        token_fingerprint=fingerprint(tag),
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=f"act_{tag}",
        connection_id=connection.id,
        name="Asosiy",
        currency="USD",
        timezone="Asia/Tashkent",
    )
    page = PageAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=f"page_{tag}",
        connection_id=connection.id,
        name="Sahifa",
        token_encrypted=b"x",
        token_fingerprint=tag,
    )
    db.add_all([account, page])
    db.commit()
    return account, page


def _switched_on(
    db: Session, owner: User, *, hours_ago: int, spent: int, fresh: bool = True
) -> None:
    account, page = _own_cabinet(db, owner)
    now = utcnow()
    started = now - timedelta(hours=hours_ago)
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            page_id=page.id,
            provider=PROVIDER,
            status="created",
            created_refs={"campaign": f"c_{owner.email}"},
            delivery_started_at=started,
        )
    )
    db.add(
        Campaign(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id=f"c_{owner.email}",
            ad_account_id=account.id,
            delivery="active",
            synced_at=now if fresh else now - timedelta(hours=12),
        )
    )
    if spent:
        db.add(
            MetricsDaily(
                owner_id=owner.id,
                provider=PROVIDER,
                ad_account_id=account.id,
                level="campaign",
                external_id=f"c_{owner.email}",
                campaign_external_id=f"c_{owner.email}",
                date=now.date(),
                spend_minor=spent,
                currency="USD",
                synced_at=now,
            )
        )
    db.commit()


def test_a_running_campaign_that_spent_nothing_in_a_day_is_a_ticket(
    db: Session,
) -> None:
    _live(db, hours_ago=24 * 3)
    cases = {
        "zero@shop.test": dict(hours_ago=26, spent=0),
        "spending@shop.test": dict(hours_ago=26, spent=500),
        "young@shop.test": dict(hours_ago=10, spent=0),
        "stale@shop.test": dict(hours_ago=26, spent=0, fresh=False),
    }
    people = {email: _client(db, email) for email in cases}
    for email, case in cases.items():
        _switched_on(db, people[email], **case)  # type: ignore[arg-type]

    assert triggers.sweep_idle(db, now=utcnow()) == 1
    ticket = _ticket(db, people["zero@shop.test"])
    assert ticket is not None and "sarf 0" in ticket.reasons[0]["detail"]
    for email in ("spending@shop.test", "young@shop.test", "stale@shop.test"):
        assert _ticket(db, people[email]) is None
    assert triggers.sweep_idle(db, now=utcnow()) == 0


def test_spending_launches_do_not_crowd_out_a_newer_idle_one(db: Session) -> None:
    """A launch that spends gets no ticket; it must not take a place in the
    batch the next hour, or older spenders hide every newer idle campaign."""
    _live(db, hours_ago=24 * 3)
    old = _client(db, "old@shop.test")
    idle = _client(db, "idle@shop.test")
    _switched_on(db, old, hours_ago=40, spent=500)
    _switched_on(db, idle, hours_ago=26, spent=0)

    assert triggers.idle_no_spend(db, now=utcnow(), limit=1) == 1
    assert _ticket(db, idle) is not None
    assert _ticket(db, old) is None


def test_plain_answers_do_not_crowd_out_a_newer_request(
    client: TestClient, db: Session
) -> None:
    _live(db)
    question = _question(db)
    boss = _staff(db, "boss@office.test", superuser=True)
    client.put(f"{URL}/{question.id}/help-options", json={"options": [0]}, headers=boss)
    fine = [_client(db, f"fine{n}@shop.test") for n in range(3)]
    for person in fine:
        _answer(db, person, question, 1)
    asks = _client(db, "asks@shop.test")
    _answer(db, asks, question, 0)

    assert triggers.survey_help(db, now=utcnow(), limit=2) == 1
    assert _ticket(db, asks) is not None


def test_the_idle_sweep_runs_every_hour() -> None:
    entries = {e["task"]: e for e in beat_schedule().values()}
    entry = entries["app.modules.boards.tasks.sweep_idle_board_task"]
    assert str(entry["schedule"]._orig_minute) == "15"
