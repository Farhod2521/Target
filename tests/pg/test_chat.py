"""The assistant against PostgreSQL: what it is told, what it may look up, and one answered turn."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from llmkit import LLMResult
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign, CampaignLaunch
from app.modules.agent.models import AgentRun, AgentSuggestion
from app.modules.billing.services import start_trial
from app.modules.businesses.models import Business
from app.modules.chat import selectors, services
from app.modules.chat.models import ChatMessage, ChatSession
from app.modules.chat.selectors.lookups import HANDLERS, answer_lookup
from app.modules.chat.selectors.scope import asked_scopes
from app.modules.leads.models import Lead, LeadForm
from app.modules.metrics.models import MetricsDaily
from core.chat import lookup_arguments as args
from tests.pg.conftest import sign_up
from tests.pg.test_cabinet_flows import _cabinet


def _account(db: Session) -> tuple[User, Any, Any]:
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    assert owner is not None
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = page.leadgen_subscribed = True
    account.is_active = account.is_current = True
    db.add(
        Business(
            user_id=owner.id,
            page_id=page.id,
            name="Bahor",
            offer_text="Tort",
            timezone="Asia/Tashkent",
            country_code="UZ",
        )
    )
    db.commit()
    start_trial(db, user=owner, now=utcnow())
    db.commit()
    return owner, account, page


def _mirror(db: Session, owner: User, account: Any, page: Any) -> None:
    now = utcnow()
    campaign = Campaign(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="c_1",
        ad_account_id=account.id,
        name="Bahor aksiyasi",
        delivery="active",
        status="ACTIVE",
        currency="USD",
        synced_at=now,
        created_time=now - timedelta(days=20),
    )
    db.add(campaign)
    db.flush()
    adset = AdSet(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="s_1",
        campaign_id=campaign.id,
        name="Toshkent 25-45",
        delivery="active",
        status="ACTIVE",
        optimization_goal_raw="LEAD_GENERATION",
        promoted_object_raw={"page_id": "page_1"},
        targeting_raw={
            "geo_locations": {"countries": ["UZ"]},
            "age_min": 25,
            "age_max": 45,
        },
        daily_budget_minor=1000,
        synced_at=now,
    )
    db.add(adset)
    db.flush()
    form = LeadForm(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="f_1",
        page_id=page.id,
        name="Buyurtma",
        questions_raw=[{"key": "phone", "type": "PHONE"}],
    )
    db.add(form)
    db.add(
        AdCreative(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id="cr_1",
            ad_account_id=account.id,
            headline="Bahorgi tort",
            message="Buyurtma bering",
            link_url="https://bahor.example",
        )
    )
    db.add(
        Ad(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id="a_1",
            adset_id=adset.id,
            name="Tort reklamasi",
            delivery="active",
            status="ACTIVE",
            creative_external_id="cr_1",
            lead_form_external_id="f_1",
            synced_at=now,
        )
    )
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            page_id=page.id,
            provider=PROVIDER,
            status="created",
            created_refs={"campaign": "c_1", "adset": ["s_1"], "ad": ["a_1"]},
        )
    )
    db.flush()
    today = now.date()
    for back in range(1, 8):
        for level, extra in (
            ("campaign", {}),
            ("adset", {"adset_external_id": "s_1"}),
            ("ad", {"adset_external_id": "s_1", "ad_external_id": "a_1"}),
        ):
            db.add(
                MetricsDaily(
                    owner_id=owner.id,
                    provider=PROVIDER,
                    external_id={"campaign": "c_1", "adset": "s_1", "ad": "a_1"}[level],
                    ad_account_id=account.id,
                    level=level,
                    campaign_external_id="c_1",
                    date=today - timedelta(days=back),
                    spend_minor=500,
                    currency="USD",
                    impressions=1000,
                    clicks=40,
                    inline_link_clicks=30,
                    leads_reported=2,
                    synced_at=now,
                    **extra,
                )
            )
    db.add(
        Lead(
            owner_id=owner.id,
            provider=PROVIDER,
            leadgen_id="l_1",
            received_at=now - timedelta(days=2),
            form_id=form.id,
            campaign_external_id="c_1",
            adset_external_id="s_1",
            ad_external_id="a_1",
            phone_e164="+998901234567",
            submitted_at=now - timedelta(days=2),
        )
    )
    db.commit()


def test_context_and_every_lookup(client: TestClient, db: Session) -> None:
    sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)
    now = utcnow()

    context = selectors.chat_context(db, owner=owner, now=now)
    rendered = context.render()
    assert "Bahor aksiyasi" in rendered
    assert "Toshkent 25-45" in rendered

    described, counted = asked_scopes(db, owner=owner)
    calls = {
        "account_overview": args.Nothing(),
        "find": args.Search(query="Tort"),
        "list_campaigns": args.CampaignList(),
        "campaign_details": args.CampaignLookup(campaign_id="c_1"),
        "audience_details": args.AdSetLookup(adset_id="s_1"),
        "ad_details": args.AdLookup(ad_id="a_1"),
        "daily_figures": args.DailyFigures(),
        "lead_counts": args.LeadCounts(),
        "lead_forms": args.FormList(),
        "recent_changes": args.Window(),
        "agent_proposals": args.Proposals(),
        "open_problems": args.Nothing(),
        "audiences": args.Nothing(),
        "preparations": args.Window(),
    }
    assert set(calls) == set(HANDLERS)
    answers = {
        name: answer_lookup(
            db,
            owner=owner,
            name=name,
            arguments=value,
            scope=described,
            now=now,
            counted=counted,
        )
        for name, value in calls.items()
    }
    assert "Bahor aksiyasi" in answers["list_campaigns"]
    assert "Tort reklamasi" in answers["ad_details"]
    assert "Buyurtma" in answers["lead_forms"]
    assert "advert" in answers["find"]
    for group in ("day", "campaign", "ad_group", "form", "page"):
        answer_lookup(
            db,
            owner=owner,
            name="lead_counts",
            arguments=args.LeadCounts(group_by=group),
            scope=described,
            now=now,
        )
    answer_lookup(
        db,
        owner=owner,
        name="daily_figures",
        arguments=args.DailyFigures(object_id="s_1"),
        scope=described,
        now=now,
    )

    assert selectors.daily_reports(db, owner=owner, now=now) is not None
    selectors.weekly_report(db, owner=owner, now=now)


@dataclass
class _Stream:
    pieces: list[str]
    result: Any = None

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield from self.pieces


class _Claude:
    def _answer(self, **asked: Any) -> _Stream:
        text = ["Sizning ", "kampaniyangiz ", "ishlayapti."]
        return _Stream(
            pieces=text,
            result=LLMResult(
                value="".join(text),
                input_tokens=10,
                output_tokens=5,
                cost_micros=1,
                currency="USD",
                latency_ms=1,
                prompt_name=asked.get("prompt_name", ""),
                prompt_version=asked.get("prompt_version", ""),
                model="test",
            ),
        )

    def stream(self, **asked: Any) -> _Stream:
        return self._answer(**asked)

    def converse(self, **asked: Any) -> _Stream:
        return self._answer(**asked)


@contextmanager
def _claude(**_: Any):  # type: ignore[no-untyped-def]
    yield _Claude()


def test_a_question_answered_and_streamed(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    headers = sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)

    screen = client.get("/api/v1/chat", headers=headers)
    assert screen.status_code == 200, screen.text
    assert screen.json()["entitled"] is True

    asked = client.post(
        "/api/v1/chat/ask", json={"question": "Kampaniyam qanday?"}, headers=headers
    )
    assert asked.status_code == 200, asked.text
    turn = asked.json()
    assert turn["session_id"]
    assert queued[-1][0].endswith("answer_chat_turn")
    rows = list(db.scalars(select(ChatMessage).order_by(ChatMessage.created_at)))
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[1].status == "pending"

    monkeypatch.setattr("app.modules.chat.services.answer.claude", _claude)
    payload = services.turn_payload(turn_id=turn["turn_id"])
    assert payload is not None and payload["lookups"] is True
    services.answer_turn(db, turn_id=turn["turn_id"], payload=payload, now=utcnow())
    db.commit()
    db.expire_all()
    answer = db.get(ChatMessage, rows[1].id)
    assert answer is not None and answer.status == "done"
    assert "ishlayapti" in answer.text
    assert db.scalar(select(ChatSession.last_message_at)) is not None

    from app.common import tokens

    token = headers["Authorization"].removeprefix("Bearer ")
    streamed = client.get(f"/api/v1/chat/stream/{turn['turn_id']}?token={token}")
    assert streamed.status_code == 200
    assert '"done": true' in streamed.text
    assert "ishlayapti" in streamed.text
    assert tokens.read(token, kind="access")

    stranger = client.get(f"/api/v1/chat/stream/{turn['turn_id']}")
    assert '"error": "denied"' in stranger.text

    thread = client.get(f"/api/v1/chat/threads/{turn['session_id']}", headers=headers)
    assert thread.status_code == 200
    assert [row["role"] for row in thread.json()["messages"]] == ["user", "assistant"]

    report = client.get("/api/v1/chat/report", headers=headers)
    assert report.status_code == 200 and report.json()["entitled"] is True


def test_a_visitor_spends_the_free_allowance(
    client: TestClient, db: Session, queued: list
) -> None:
    first = client.post(
        "/api/v1/chat/ask", json={"question": "Reklama nima?", "guest_id": "g1"}
    )
    assert first.status_code == 200, first.text
    assert first.json()["session_id"] == ""
    assert first.json()["left"] == 9
    assert db.scalar(select(ChatMessage.id)) is None


def test_a_choice_is_rechecked_before_it_is_carried_out(
    client: TestClient, db: Session, queued: list
) -> None:
    headers = sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)
    now = utcnow()
    run = AgentRun(owner_id=owner.id, status="done", finished_at=now)
    db.add(run)
    db.flush()
    suggestion = AgentSuggestion(
        owner_id=owner.id,
        target_provider=PROVIDER,
        target_level="adset",
        target_external_id="s_1",
        run_id=run.id,
        kind="pause",
        rule="no_leads",
        reason="Pul ketyapti, murojaat yo'q.",
        evidence={"spend_minor": 3500, "currency": "USD"},
        payload={},
        status="pending",
        expires_at=now + timedelta(days=1),
    )
    db.add(suggestion)
    db.commit()

    from app.modules.chat.selectors import still_open

    assert still_open(db, owner=owner, pks=[str(suggestion.id)]) == {str(suggestion.id)}
    pressed = client.post(f"/api/v1/chat/choices/{suggestion.id}", headers=headers)
    assert pressed.status_code == 200, pressed.text
    assert pressed.json()["state"] in {"refused", "working"}
    state = client.get(f"/api/v1/chat/choices/{suggestion.id}", headers=headers)
    assert state.status_code == 200
    assert state.json()["state"] in {"done", "working"}


def test_a_refused_launch_is_explained_and_the_answer_kept(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from app.modules.chat.models import RefusalAnswer

    headers = sign_up(client)
    owner, account, page = _account(db)
    launch = CampaignLaunch(
        owner_id=owner.id,
        ad_account_id=account.id,
        page_id=page.id,
        provider=PROVIDER,
        status="failed",
        error_code="provider",
        error_message="(#100) Invalid parameter (subcode 1885624)",
        error_detail={"title": "Noto'g'ri sozlama", "message": "Byudjet juda kichik"},
    )
    db.add(launch)
    db.commit()

    asked = client.post(
        "/api/v1/chat/ask", json={"launch": str(launch.id)}, headers=headers
    )
    assert asked.status_code == 200, asked.text
    turn = asked.json()
    assert turn["left"] == -1
    assert queued[-1][0].endswith("answer_refusal_turn")

    monkeypatch.setattr("app.modules.chat.services.refusal.claude", _claude)
    payload = services.turn_payload(turn_id=turn["turn_id"])
    assert payload is not None
    services.answer_refusal(db, turn_id=turn["turn_id"], payload=payload, now=utcnow())
    db.commit()
    rows = list(db.scalars(select(ChatMessage).order_by(ChatMessage.created_at)))
    assert rows[-1].status == "done"
    kept = db.scalar(select(RefusalAnswer))
    if kept is not None:
        assert kept.hits >= 1
