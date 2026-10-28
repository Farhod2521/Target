"""The actions screen: the waiting list, the bell, the badges and the record."""

from datetime import timedelta

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, CampaignLaunch
from app.modules.agent.constants import HISTORY_PAGE, RunStatus, SuggestionStatus
from app.modules.agent.models import AgentRun, AgentSuggestion
from app.modules.billing.models import Subscription
from app.modules.billing.services import start_trial
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.notifications.models import InboxSeen
from tests.pg.conftest import sign_up
from tests.pg.test_ads_manage import _mirror
from tests.pg.test_cabinet_flows import _cabinet

URL = "/api/v1/actions"


def _owner(
    client: TestClient, db: Session, *, days: int = 30, prepared: bool = True
) -> tuple[dict[str, str], User]:
    """A cabinet with a subscription ``days`` long and nothing else."""
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    subscription = start_trial(db, user=user, now=utcnow())
    subscription.expires_at = utcnow() + timedelta(days=days, hours=1)
    if prepared:
        subscription.setup_completed_at = utcnow()
    db.commit()
    return auth, user


def _page_with_campaign(db: Session, user: User) -> tuple[AdAccount, PageAccount]:
    account, page = _cabinet(db, user)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    _mirror(db, user, account.id)
    db.add(
        CampaignLaunch(
            owner_id=user.id,
            ad_account_id=account.id,
            page_id=page.id,
            provider=PROVIDER,
            status="created",
            created_refs={"campaign": "c_1", "adset": ["s_1"], "ad": ["a_1"]},
        )
    )
    db.commit()
    return account, page


def _run(db: Session, user: User) -> AgentRun:
    run = AgentRun(owner_id=user.id, window_days=7, status=RunStatus.DONE)
    db.add(run)
    db.commit()
    return run


def _suggestion(db: Session, user: User, run: AgentRun, **extra: object) -> None:
    fields: dict[str, object] = {
        "owner_id": user.id,
        "run_id": run.id,
        "kind": "pause",
        "rule": "wasting",
        "reason": "Sarf bor, natija yo'q.",
        "target_provider": PROVIDER,
        "target_level": "adset",
        "target_external_id": "s_1",
        "expires_at": utcnow() + timedelta(hours=48),
        "status": SuggestionStatus.PENDING,
    }
    db.add(AgentSuggestion(**(fields | extra)))
    db.commit()


def _all(body: dict) -> list[dict]:
    return [*body["urgent"], *body["decisions"], *body["news"]]


def test_empty_inbox(client: TestClient, db: Session) -> None:
    auth, _user = _owner(client, db)

    screen = client.get(URL, headers=auth)
    assert screen.status_code == 200, screen.text
    body = screen.json()
    assert _all(body) == []
    assert body["cards"] == [] and body["history"] == [] and body["more"] is False
    assert body["counts"] == {"new": 0, "waiting": 0}
    assert body["summary"] == {"standing": "", "last_run_at": None, "broken": False}

    bell = client.post(f"{URL}/bell", headers=auth).json()
    assert bell == {
        "items": [],
        "more": 0,
        "watching": False,
        "all_href": "/app/amallar/",
    }
    assert client.get(f"{URL}/counts", headers=auth).json() == {"new": 0, "waiting": 0}


def test_a_cabinet_that_never_opened_a_plan(client: TestClient, db: Session) -> None:
    auth = sign_up(client)
    body = client.get(URL, headers=auth).json()
    [item] = body["urgent"]
    assert item["key"] == "subscription:none"
    assert item["title"] == "Tarif hali ochilmagan"
    assert item["href"] == "/app/billing/"


def test_unfinished_preparation(client: TestClient, db: Session) -> None:
    auth, _user = _owner(client, db, prepared=False)

    body = client.get(URL, headers=auth).json()

    setup = [item for item in _all(body) if item["kind"] == "setup"]
    assert len(setup) == 1
    assert setup[0]["key"].startswith("setup:")
    assert setup[0]["title"] == "Sozlash tugallanmagan"
    assert setup[0]["href"] == "/app/start/"


def test_unread_support_reply(client: TestClient, db: Session) -> None:
    from app.modules.supportchat.models import SupportConversation

    auth, user = _owner(client, db)
    db.add(SupportConversation(owner_id=user.id, last_office_at=utcnow()))
    db.commit()

    body = client.get(URL, headers=auth).json()

    support = [item for item in _all(body) if item["kind"] == "support"]
    assert len(support) == 1
    assert support[0]["title"] == "Yordam xizmati javob berdi"
    assert support[0]["href"] == "/app/yordam/"

    client.get("/api/v1/support", headers=auth)
    after = client.get(URL, headers=auth).json()
    assert [item for item in _all(after) if item["kind"] == "support"] == []


def test_subscription_ending(client: TestClient, db: Session) -> None:
    auth, _user = _owner(client, db, days=2)
    expires = db.scalar(select(Subscription.expires_at))

    [item] = client.get(URL, headers=auth).json()["decisions"]
    assert item["kind"] == "subscription" and item["level"] == "decision"
    assert item["key"] == f"subscription:{expires:%Y-%m-%d}:3"
    assert item["title"] == "Obuna muddati tugayapti"
    assert item["body"].startswith("3 kundan keyin platformada yaratilgan reklamalar")
    assert item["action"] == "Yangilash" and item["href"] == "/app/billing/"
    assert item["ask"] == {
        "label": "AI dan so'rash",
        "href": f"/app/chat/?item=subscription%3A{expires:%Y-%m-%d}%3A3",
    }


def test_broken_meta_connection(client: TestClient, db: Session) -> None:
    auth, user = _owner(client, db)
    account, _page = _cabinet(db, user)
    account.connection.status = ConnectionStatus.EXPIRED
    db.commit()

    [item] = client.get(URL, headers=auth).json()["urgent"]
    assert item["kind"] == "connection"
    assert item["key"] == f"connection:{account.connection_id}:expired"
    assert item["title"] == "Facebook ulanishi uzildi"
    assert item["body"] == "Yangi mijozlar kelmayapti va raqamlar yangilanmayapti."
    assert item["action"] == "Qayta ulash"
    assert item["href"] == "/app/connections/"
    assert item["method"] == "get" and item["subject"] is None


def test_a_pending_suggestion(client: TestClient, db: Session) -> None:
    auth, user = _owner(client, db)
    _page_with_campaign(db, user)
    _suggestion(db, user, _run(db, user))

    body = client.get(URL, headers=auth).json()
    # Drawn by the proposals block with its own buttons, never twice.
    assert all(item["kind"] != "suggestion" for item in _all(body))
    [card] = body["cards"]
    assert card["kind"] == "pause"
    assert body["counts"]["waiting"] == 1

    bell = client.post(f"{URL}/bell", headers=auth).json()
    [line] = bell["items"]
    assert line["kind"] == "suggestion" and line["level"] == "decision"
    assert line["title"] == "To'xtatish" and line["body"] == "Sarf bor, natija yo'q"
    assert line["subject"]["id"] == "s_1" and line["subject"]["level"] == "adset"
    assert line["fresh"] is True and line["link"] == "/app/amallar/"

    proposals = client.get(f"{URL}/proposals", headers=auth).json()
    assert [row["pk"] for row in proposals["cards"]] == [card["pk"]]
    assert proposals["poll_seconds"] > 0 and "history" in proposals


def test_refused_advert(client: TestClient, db: Session) -> None:
    auth, user = _owner(client, db)
    _page_with_campaign(db, user)
    ad = db.scalar(select(Ad).where(Ad.external_id == "a_1"))
    assert ad is not None
    ad.review_feedback = {"overall": {"Alcohol": "Ads may not promote alcohol."}}
    db.commit()

    [item] = client.get(URL, headers=auth).json()["urgent"]
    assert item["kind"] == "refusal"
    assert (
        item["key"].startswith("refusal:") and len(item["key"]) == len("refusal:") + 8
    )
    assert item["title"] == "Meta reklamani rad etdi"
    assert item["body"].endswith(
        "Meta'ning so'zlari: Alcohol: Ads may not promote alcohol."
    )
    assert item["action"] == "Reklamani ochish"
    assert item["href"].startswith("/app/campaigns/") and item["href"].endswith("/")
    assert item["subject"]["id"] == "a_1" and item["subject"]["name"] == "Reklama"


def test_counts_and_bell_agree_with_the_inbox(client: TestClient, db: Session) -> None:
    auth, user = _owner(client, db, days=2)
    account, _page = _page_with_campaign(db, user)
    account.connection.status = ConnectionStatus.REVOKED
    db.commit()
    _suggestion(db, user, _run(db, user))

    screen = client.get(URL, headers=auth).json()
    kinds = {item["kind"] for item in _all(screen)}
    assert kinds == {"connection", "subscription"}
    total = len(_all(screen)) + len(screen["cards"])
    assert screen["counts"] == {"new": total, "waiting": total}
    assert client.get(f"{URL}/counts", headers=auth).json() == screen["counts"]

    bell = client.post(f"{URL}/bell", headers=auth).json()
    assert len(bell["items"]) == total and bell["more"] == 0
    assert [line["level"] for line in bell["items"]] == [
        "urgent",
        "decision",
        "decision",
    ]
    assert all(line["fresh"] for line in bell["items"])
    assert len(db.scalars(select(InboxSeen)).all()) == total

    # Opening the bell is what clears it; the badge counts what is unanswered.
    assert client.get(f"{URL}/counts", headers=auth).json() == {
        "new": 0,
        "waiting": total,
    }
    again = client.post(f"{URL}/bell", headers=auth).json()
    assert not any(line["fresh"] for line in again["items"])


def test_history_paging(client: TestClient, db: Session) -> None:
    auth, user = _owner(client, db)
    _page_with_campaign(db, user)
    run = _run(db, user)
    now = utcnow()
    for index in range(HISTORY_PAGE + 2):
        _suggestion(
            db,
            user,
            run,
            status=SuggestionStatus.REJECTED,
            decided_at=now - timedelta(hours=index + 1),
        )

    first = client.get(URL, headers=auth).json()
    assert len(first["history"]) == HISTORY_PAGE and first["more"] is True
    cursor = first["next_before"]
    assert cursor == first["history"][-1]["decided_at"]

    second = client.get(f"{URL}/history", params={"before": cursor}, headers=auth)
    assert second.status_code == 200, second.text
    rest = second.json()
    assert len(rest["history"]) == 2 and rest["more"] is False
    assert rest["next_before"] is None
    seen = {row["pk"] for row in first["history"]}
    assert not seen & {row["pk"] for row in rest["history"]}

    # A cursor that will not parse is the first page again, not an error.
    broken = client.get(f"{URL}/history", params={"before": "nonsense"}, headers=auth)
    assert broken.status_code == 200
    assert [row["pk"] for row in broken.json()["history"]] == [
        row["pk"] for row in first["history"]
    ]
