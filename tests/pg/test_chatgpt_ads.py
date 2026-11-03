"""The ChatGPT Ads section: connecting by key, the live screen, presses, a launch.

OpenAI is a fake answering by path; nothing leaves the process.
"""

import dataclasses
import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from openaiadskit import PROVIDER as CHATGPT
from openaiadskit.adapter import bundle
from openaiadskit.campaigns import OpenAICampaigns
from openaiadskit.client import AdsClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.config import settings
from app.common.crypto import decrypt
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.models import Plan, Subscription
from app.modules.integrations.models import AdAccount, ProviderConnection

KEY = "sk-ads-live-1"
AD_ACCOUNT = {
    "id": "adacct_1",
    "name": "Gul do'koni",
    "url": "https://gul.uz",
    "preview_url": None,
    "status": "active",
    "timezone": "Asia/Tashkent",
    "currency_code": "USD",
    "review": {"status": "approved"},
}


class Wire:
    """A fake OpenAI: answers by ``(method, path)`` and remembers every request."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Any] = {("GET", "ad_account"): AD_ACCOUNT}
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        answer = self.routes.get(
            (request.method, request.url.path.removeprefix("/v1/"))
        )
        if answer is None:
            return httpx.Response(404, json={"error": {"message": "no such thing"}})
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def paths(self) -> list[str]:
        return [f"{r.method} {r.url.path.removeprefix('/v1/')}" for r in self.seen]


def _page(*rows: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "list",
        "data": list(rows),
        "first_id": None,
        "last_id": None,
        "has_more": False,
    }


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Iterator[Wire]:
    from adskit import registry

    from app.modules.chatgpt import services

    fake = Wire()

    def client(*, api_key: str, http: httpx.Client | None = None) -> AdsClient:
        return AdsClient(api_key=api_key, http=fake.http())

    monkeypatch.setattr(services, "AdsClient", client)
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "chatgpt_ads_enabled", True)
    monkeypatch.setattr(settings, "chatgpt_ads_dry_run", False)
    registry.register(
        CHATGPT,
        dataclasses.replace(
            bundle(), campaigns=OpenAICampaigns(http=fake.http(), rehearse_writes=False)
        ),
    )
    yield fake
    registry.register(CHATGPT, bundle(rehearse_writes=settings.chatgpt_ads_dry_run))


def _owner(db: Session, email: str = "gpt@example.com") -> tuple[User, dict[str, str]]:
    now = utcnow()
    owner = User(email=email, full_name="Ega", password="!", date_joined=now)
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
    db.commit()
    token = tokens.issue(subject=str(owner.id), kind="access", now=now)
    return owner, {"Authorization": f"Bearer {token}"}


def _connect(client: TestClient, auth: dict[str, str]) -> httpx.Response:
    return client.post("/api/v1/chatgpt/connect", json={"apiKey": KEY}, headers=auth)


def test_the_section_is_hidden_until_switched_on(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, auth = _owner(db)
    monkeypatch.setattr(settings, "chatgpt_ads_enabled", False)
    monkeypatch.setattr(settings, "chatgpt_ads_users", [])

    card = client.get("/api/v1/chatgpt/card", headers=auth)
    screen = client.get("/api/v1/chatgpt/screen", headers=auth)

    assert card.status_code == 200 and card.json()["available"] is False
    assert screen.status_code == 404
    assert screen.json()["code"] == "chatgpt_ads_unavailable"


def test_a_key_is_checked_kept_encrypted_and_names_its_account(
    client: TestClient, db: Session, wire: Wire
) -> None:
    owner, auth = _owner(db)

    answer = _connect(client, auth)

    assert answer.status_code == 200, answer.text
    assert answer.json()["connected"] is True
    assert answer.json()["account"] == {
        "id": "adacct_1",
        "name": "Gul do'koni",
        "currency": "USD",
        "timezone": "Asia/Tashkent",
    }
    connection = db.scalar(
        select(ProviderConnection).where(ProviderConnection.provider == CHATGPT)
    )
    assert connection is not None and connection.kind == "api_key"
    assert decrypt(connection.token_encrypted) == KEY
    assert KEY.encode() not in connection.token_encrypted
    account = db.scalar(select(AdAccount).where(AdAccount.provider == CHATGPT))
    assert account is not None and account.owner_id == owner.id
    # Out of every sweep's sight: none of them speaks ChatGPT yet.
    assert (account.is_active, account.is_current) == (False, True)
    assert wire.seen[0].headers["Authorization"] == f"Bearer {KEY}"


def test_a_refused_key_says_so(client: TestClient, db: Session, wire: Wire) -> None:
    _, auth = _owner(db)
    wire.routes[("GET", "ad_account")] = httpx.Response(
        401, json={"error": {"message": "invalid key"}}
    )

    answer = _connect(client, auth)

    assert answer.status_code == 400
    assert answer.json()["code"] == "chatgpt_key_rejected"


def test_one_account_one_cabinet_until_it_is_let_go(
    client: TestClient, db: Session, wire: Wire
) -> None:
    _, first = _owner(db, "first@example.com")
    _, second = _owner(db, "second@example.com")
    assert _connect(client, first).status_code == 200

    taken = _connect(client, second)
    client.post("/api/v1/chatgpt/disconnect", headers=first)
    moved = _connect(client, second)

    assert taken.status_code == 409 and taken.json()["code"] == "chatgpt_account_taken"
    assert moved.status_code == 200, moved.text


def test_the_screen_reads_campaigns_and_figures_live(
    client: TestClient, db: Session, wire: Wire
) -> None:
    _, auth = _owner(db)
    _connect(client, auth)
    wire.routes[("GET", "campaigns")] = _page(
        {
            "id": "c1",
            "name": "Gul",
            "status": "active",
            "budget": {"daily_spend_limit_micros": 10_000_000},
            "bidding_type": "clicks",
            "serving_issues": [{"code": "ad_in_review"}],
        },
        {"id": "c2", "name": "Eski", "status": "archived", "budget": {}},
    )
    wire.routes[("GET", "ad_account/insights")] = _page(
        {
            "id": "r",
            "start_time": 1,
            "end_time": 2,
            "campaign_id": "c1",
            "impressions": 1000,
            "clicks": 40,
            "spend": 12.5,
        }
    )

    answer = client.get("/api/v1/chatgpt/screen?period=30", headers=auth)

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["period"] == "30"
    assert body["account"]["reviewStatus"] == "approved"
    assert [c["id"] for c in body["campaigns"]] == ["c1"]
    shown = body["campaigns"][0]
    assert shown["delivery"] == "pending"
    assert shown["dailyBudget"] == {"minor": 1000, "currency": "USD", "exponent": 2}
    assert shown["issues"][0]["code"] == "ad_in_review"
    assert shown["figures"]["clicks"] == 40
    assert shown["figures"]["spend"]["minor"] == 1250
    assert shown["figures"]["cpc"]["minor"] == 31
    assert body["totals"]["impressions"] == 1000


def test_a_campaign_shows_where_it_runs_so_a_copy_can_keep_it(
    client: TestClient, db: Session, wire: Wire
) -> None:
    _, auth = _owner(db)
    _connect(client, auth)
    wire.routes |= {
        ("GET", "campaigns"): _page(
            {
                "id": "c1",
                "name": "Gul",
                "status": "active",
                "budget": {"daily_spend_limit_micros": 10_000_000},
                "targeting": {
                    "locations": {"countries": ["UZ"], "include": [{"id": "2001959"}]}
                },
            }
        ),
        ("GET", "ad_groups"): _page(),
        ("GET", "ad_account/insights"): _page(),
    }

    answer = client.get("/api/v1/chatgpt/campaigns/c1", headers=auth)

    assert answer.status_code == 200, answer.text
    assert answer.json()["locations"] == {
        "countries": ["UZ"],
        "placeIds": ["2001959"],
        "places": [{"id": "2001959", "name": ""}],
    }


def test_the_connections_page_carries_the_chatgpt_card(
    client: TestClient, db: Session, wire: Wire
) -> None:
    _, auth = _owner(db)
    before = client.get("/api/v1/connections", headers=auth).json()["chatgpt"]
    _connect(client, auth)
    after = client.get("/api/v1/connections", headers=auth).json()["chatgpt"]
    client.post("/api/v1/chatgpt/disconnect", headers=auth)
    gone = client.get("/api/v1/connections", headers=auth).json()["chatgpt"]

    assert before["chatgpt_ads_on"] is True and before["connected"] is False
    assert before["connection"] is None
    assert after["connected"] is True
    assert after["account"]["external_id"] == "adacct_1"
    assert after["connection"]["status"] == "active"
    assert gone["connected"] is False and gone["account"] is None
    assert gone["connection"]["status"] == "revoked"


def test_a_press_goes_to_openai_and_a_rehearsal_does_not(
    client: TestClient, db: Session, wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adskit import registry

    _, auth = _owner(db)
    _connect(client, auth)
    wire.routes[("POST", "campaigns/c1/pause")] = {"id": "c1", "status": "paused"}
    press = {"level": "campaign", "id": "c1", "wanted": "pause"}

    sent = client.post("/api/v1/chatgpt/switch", json=press, headers=auth)
    registry.register(
        CHATGPT,
        dataclasses.replace(
            bundle(), campaigns=OpenAICampaigns(http=wire.http(), rehearse_writes=True)
        ),
    )
    before = len(wire.seen)
    rehearsed = client.post("/api/v1/chatgpt/switch", json=press, headers=auth)

    assert sent.status_code == 200, sent.text
    assert sent.json()["dryRun"] is False
    assert "POST campaigns/c1/pause" in wire.paths()
    assert rehearsed.json()["dryRun"] is True
    assert len(wire.seen) == before


def test_a_refusal_carries_openai_s_words(
    client: TestClient, db: Session, wire: Wire
) -> None:
    _, auth = _owner(db)
    _connect(client, auth)
    wire.routes[("POST", "campaigns/c1/archive")] = httpx.Response(
        400, json={"error": {"message": "campaign is locked", "code": "locked"}}
    )

    answer = client.post(
        "/api/v1/chatgpt/archive", json={"level": "campaign", "id": "c1"}, headers=auth
    )

    assert answer.status_code == 422
    body = answer.json()
    assert body["code"] == "provider_refused"


NEW: dict[str, Any] = {
    "name": "Gul yetkazib berish",
    "dailyBudget": {"minor": 1000, "currency": "USD", "exponent": 2},
    "title": "Toshkentda gul yetkazish",
    "body": "Bir soatda eshigingizgacha.",
    "targetUrl": "https://gul.uz",
    "countries": ["uz"],
    "contextHints": ["tug'ilgan kunga gul"],
    "requestId": "r-1",
}


def test_a_launch_makes_the_campaign_its_group_and_its_card(
    client: TestClient, db: Session, wire: Wire
) -> None:
    _, auth = _owner(db)
    _connect(client, auth)
    wire.routes |= {
        ("POST", "campaigns"): {"id": "c9", "status": "paused"},
        ("POST", "ad_groups"): {"id": "g9"},
        ("POST", "ads"): {"id": "a9", "review_status": "in_review"},
        ("POST", "campaigns/c9/activate"): {"id": "c9", "status": "active"},
    }

    answer = client.post("/api/v1/chatgpt/campaigns", json=NEW, headers=auth)

    assert answer.status_code == 201, answer.text
    assert answer.json()["campaignId"] == "c9"
    assert answer.json()["reviewStatus"] == "in_review"
    sent = next(r for r in wire.seen if r.url.path == "/v1/campaigns")
    body = json.loads(sent.content)
    assert body["budget"] == {"daily_spend_limit_micros": 10_000_000}
    assert body["targeting"]["locations"]["countries"] == ["UZ"]
    assert sent.headers["Idempotency-Key"].endswith(":r-1:campaign")


def test_a_rehearsed_launch_sends_nothing_and_shows_what_would_go(
    client: TestClient, db: Session, wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, auth = _owner(db)
    _connect(client, auth)
    monkeypatch.setattr(settings, "chatgpt_ads_dry_run", True)
    before = len(wire.seen)

    answer = client.post("/api/v1/chatgpt/campaigns", json=NEW, headers=auth)

    assert answer.status_code == 201, answer.text
    assert answer.json()["dryRun"] is True
    assert answer.json()["sent"]["name"] == "Gul yetkazib berish"
    assert len(wire.seen) == before


def test_a_launch_rule_is_named_by_its_field(
    client: TestClient, db: Session, wire: Wire
) -> None:
    _, auth = _owner(db)
    _connect(client, auth)

    answer = client.post(
        "/api/v1/chatgpt/campaigns", json=NEW | {"title": "x" * 51}, headers=auth
    )

    assert answer.status_code == 422
    assert answer.json()["code"] == "invalid_input"
    assert "title" in json.dumps(answer.json())
