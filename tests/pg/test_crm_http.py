"""The CRM over HTTP against PostgreSQL: the setup wizard, a closed card, the
seats a manager needs, and what must be refused rather than answered 500."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.billing.models import Plan, Subscription
from app.modules.crm.models import CrmCard
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PagePair,
    ProviderConnection,
)
from app.modules.leads.models import Lead, LeadForm

CRM = "/api/v1/crm"
PASSWORD = "Xk9$mQ2vLp7w"
LATER = "2030-01-01T10:00:00Z"


def _auth(user: User) -> dict[str, str]:
    token = tokens.issue(subject=str(user.id), kind="access", now=utcnow())
    return {"Authorization": f"Bearer {token}"}


def _owner(db: Session, *, status: str = "active") -> User:
    """A paid owner with one pair, a launch of ours and three leads from it."""
    now = utcnow()
    owner = User(
        email="crm@example.com", full_name="Ega", password="!", date_joined=now
    )
    db.add(owner)
    db.flush()
    plan = Plan(price=100, max_adsets=10, llm_cost_limit_minor=0)
    db.add(plan)
    db.flush()
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=plan.id,
            status=status,
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
    page = PageAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="page_1",
        connection_id=connection.id,
        name="Sahifa",
        token_encrypted=b"x",
        token_fingerprint="p1",
        is_active=True,
        is_current=True,
    )
    db.add_all([account, page])
    db.flush()
    db.add(PagePair(owner_id=owner.id, page_id=page.id, ad_account_id=account.id))
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            page_id=page.id,
            provider=PROVIDER,
            status="created",
            created_refs={"campaign": "c_1"},
        )
    )
    form = LeadForm(
        owner_id=owner.id, provider=PROVIDER, external_id="f_1", page_id=page.id
    )
    db.add(form)
    db.flush()
    for n in range(3):
        db.add(
            Lead(
                owner_id=owner.id,
                provider=PROVIDER,
                leadgen_id=f"lid{n}",
                form_id=form.id,
                campaign_external_id="c_1",
                ad_external_id="ad_1",
                phone_e164=f"+99890000000{n}",
                full_name=f"lid{n}",
                submitted_at=now - timedelta(hours=2),
                received_at=now - timedelta(hours=2),
            )
        )
    db.commit()
    return owner


def _stages_step(client: TestClient, head: dict[str, str]) -> dict[str, Any]:
    answer = client.post(
        f"{CRM}/setup/1",
        headers=head,
        json={
            "presets": ["new", "working", "won", "lost"],
            "columns": ["new", "working", "won", "lost"],
        },
    )
    assert answer.status_code == 200
    return answer.json()


def _running(client: TestClient, head: dict[str, str]) -> dict[str, Any]:
    """The wizard walked to the end, alone: every lead lands in the first column."""
    _stages_step(client, head)
    assert client.post(f"{CRM}/setup/skip-members", headers=head).status_code == 200
    step = client.post(
        f"{CRM}/setup/3", headers=head, json={"since": "month", "every_ad": True}
    )
    assert step.status_code == 200
    assert client.post(f"{CRM}/setup/4", headers=head, json={}).status_code == 200
    return client.get(CRM, headers=head).json()


def _member(
    client: TestClient, head: dict[str, str], email: str
) -> tuple[dict[str, Any], dict[str, str]]:
    added = client.post(
        f"{CRM}/settings/members",
        headers=head,
        json={"name": email, "email": email, "password": PASSWORD},
    )
    assert added.status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return added.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_working_alone_moves_the_wizard_on(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    assert client.post(f"{CRM}/setup/skip-members", headers=head).status_code == 409
    _stages_step(client, head)

    answer = client.post(f"{CRM}/setup/skip-members", headers=head)

    assert answer.status_code == 200
    settings = client.get(f"{CRM}/settings", headers=head).json()
    assert settings["setup"]["step"] == 3
    assert settings["setup"]["distribution"] == "manual"


def test_a_closed_card_takes_no_more_work(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    url = f"{CRM}/cards/{card}"
    assert client.post(f"{url}/win", headers=head, json={"amount": "150"}).is_success

    refused = [
        client.post(f"{url}/win", headers=head, json={"amount": "7"}),
        client.post(f"{url}/note", headers=head, json={"text": "yopiq"}),
        client.post(f"{url}/no-answer", headers=head),
        client.post(f"{url}/due", headers=head, json={"due": LATER}),
        client.post(f"{url}/due/done", headers=head),
        client.post(f"{url}/take", headers=head),
    ]

    assert [r.json().get("code") for r in refused] == ["card_is_closed"] * 6
    view = client.get(url, headers=head).json()
    assert view["card"]["won_amount_minor"] == 15000
    assert view["card"]["attempts"] == 0


def test_a_closed_card_may_still_change_outcome_and_hands(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    url = f"{CRM}/cards/{card}"
    reason = client.get(f"{CRM}/settings", headers=head).json()["reasons"][0]["id"]
    client.post(f"{url}/win", headers=head, json={"amount": "150"})

    lost = client.post(f"{url}/lose", headers=head, json={"reason": reason})
    again = client.post(f"{url}/lose", headers=head, json={"reason": reason})
    won = client.post(f"{url}/win", headers=head, json={"amount": "90"})
    held = client.post(f"{url}/assign", headers=head, json={"assignee": str(owner.id)})

    assert lost.status_code == won.status_code == held.status_code == 200
    assert again.json()["code"] == "card_is_closed"
    assert won.json()["won_amount_minor"] == 9000


def test_seats_are_told_true(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    assert client.get(f"{CRM}/settings", headers=head).json()["seat_open"] is True
    first, _ = _member(client, head, "bir@example.com")
    assert client.get(f"{CRM}/settings", headers=head).json()["seat_open"] is False

    second, signed_in = _member(client, head, "ikki@example.com")

    assert first["seated"] is True
    assert second["seated"] is False
    assert client.get(CRM, headers=signed_in).json() == {"detail": {"crm": "seat"}}
    url = f"{CRM}/settings/members/{second['id']}"
    edited = client.put(url, headers=head, json={"name": "Ikki"})
    assert edited.json()["seated"] is False
    reset = client.post(f"{url}/password", headers=head, json={"password": PASSWORD})
    assert reset.json()["seated"] is False
    view = client.get(f"{CRM}/cards/{card}", headers=head).json()
    assert sorted(m["seated"] for m in view["members"]) == [False, True]

    handed = client.post(
        f"{CRM}/cards/{card}/assign",
        headers=head,
        json={"assignee": second["user"]["id"]},
    )

    assert handed.json()["code"] == "member_not_seated"


def test_a_trial_has_no_seat_open(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db, status="trial"))
    _running(client, head)

    assert client.get(f"{CRM}/settings", headers=head).json()["seat_open"] is False


def test_a_manager_is_sent_to_the_board(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    _running(client, head)
    _, signed_in = _member(client, head, "bir@example.com")
    client.post(
        f"{CRM}/password",
        headers=signed_in,
        json={"password": PASSWORD + "1", "again": PASSWORD + "1"},
    )
    board = client.get(CRM, headers=head).json()
    client.post(
        f"{CRM}/cards/{board['columns'][0]['cards'][0]['id']}/assign",
        headers=head,
        json={"assignee": ""},
    )

    # «Men o'zim beraman» (the lone owner's setting): nothing waits for a manager.
    assert client.get(f"{CRM}/nav", headers=signed_in).json()["attention"] == 0
    claim = client.post(
        f"{CRM}/settings/distribution", headers=head, json={"distribution": "claim"}
    )
    assert claim.status_code == 200

    nav = client.get(f"{CRM}/nav", headers=signed_in).json()

    assert nav == {"url": "/app/crm/", "attention": 3}


@pytest.mark.parametrize("email", ["notanemail", "", "a@b"])
def test_a_manager_needs_a_real_email(
    client: TestClient, db: Session, email: str
) -> None:
    head = _auth(_owner(db))
    _running(client, head)

    answer = client.post(
        f"{CRM}/settings/members",
        headers=head,
        json={"name": "V", "email": email, "password": PASSWORD},
    )

    assert answer.json()["code"] == "bad_email"


def test_bad_input_is_refused_not_a_crash(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    url = f"{CRM}/cards/{board['columns'][0]['cards'][0]['id']}"

    huge = client.post(f"{url}/win", headers=head, json={"amount": "9" * 40})
    vast = client.post(f"{url}/win", headers=head, json={"amount": "1e999999"})
    naive = client.post(f"{url}/due", headers=head, json={"due": "2030-01-01T10:00:00"})
    nul = client.get(CRM, headers=head, params={"q": "a\x00b"})
    note = client.post(f"{url}/note", headers=head, json={"text": "a\x00b"})
    kpi = client.post(
        f"{CRM}/settings/members",
        headers=head,
        json={
            "name": "V",
            "email": "v@example.com",
            "password": PASSWORD,
            "kpi_fix": "9" * 40,
        },
    )
    banana = client.post(
        f"{CRM}/settings/state", headers=head, json={"state": "banana"}
    )

    assert huge.json()["code"] == vast.json()["code"] == "amount_too_big"
    assert naive.status_code == 422
    assert nul.status_code == 200
    assert note.json()["last_note"] == "ab"
    assert kpi.json()["code"] == "bad_kpi"
    assert banana.status_code == 422
    assert client.get(CRM, headers=head).json()["running"] is True


def _junk(board: dict[str, Any]) -> dict[str, Any]:
    return next(c["stage"] for c in board["columns"] if c["stage"]["kind"] == "junk")


def test_every_new_board_ends_in_the_unqualified_column(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)

    last = board["columns"][-1]["stage"]

    assert (last["kind"], last["name"]) == ("junk", "Sifatsiz lid")
    assert [c["stage"]["kind"] for c in board["columns"][-3:]] == [
        "won",
        "lost",
        "junk",
    ]


def test_the_unqualified_column_cannot_be_taken_away(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    junk = _junk(_running(client, head))
    url = f"{CRM}/settings/stages/{junk['id']}"

    refused = [
        client.delete(url, headers=head),
        client.post(f"{url}/move", headers=head, json={"way": "up"}),
        client.put(
            url, headers=head, json={"name": "Boshqa nom", "color": junk["color"]}
        ),
    ]
    painted = client.put(
        url, headers=head, json={"name": junk["name"], "color": "#C2262E"}
    )
    added = client.post(
        f"{CRM}/settings/stages", headers=head, json={"name": "Yangi", "color": ""}
    )
    quality = client.post(
        f"{CRM}/settings/quality", headers=head, json={"quality": [junk["id"]]}
    )

    assert [r.json().get("code") for r in refused] == ["stage_locked"] * 3
    assert painted.status_code == added.status_code == quality.status_code == 200
    kinds = [
        c["stage"]["kind"] for c in client.get(CRM, headers=head).json()["columns"]
    ]
    assert kinds[-1] == "junk"
    assert not next(s for s in quality.json()["stages"] if s["kind"] == "junk")[
        "counts_as_quality"
    ]


def test_a_card_dropped_in_unqualified_closes_without_a_question(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    url = f"{CRM}/cards/{card}"
    junk = _junk(board)
    client.post(f"{url}/due", headers=head, json={"due": LATER})

    moved = client.post(f"{url}/move", headers=head, json={"to": junk["id"]})

    assert moved.status_code == 200
    assert moved.json()["closed_at"] is not None
    assert moved.json()["due_at"] is None
    view = client.get(url, headers=head).json()
    assert view["can_work"] is False
    assert view["can_move"] is True
    assert [line["kind"] for line in view["history"]][:2] == ["unqualified", "moved"]
    note = client.post(f"{url}/note", headers=head, json={"text": "x"})
    assert note.json()["code"] == "card_is_closed"


def test_a_mistaken_unqualified_goes_back_and_qualifies_again(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    url = f"{CRM}/cards/{card}"
    working = next(c["stage"] for c in board["columns"] if c["stage"]["kind"] == "open")
    client.post(
        f"{CRM}/settings/quality", headers=head, json={"quality": [working["id"]]}
    )
    assert client.post(f"{url}/move", headers=head, json={"to": working["id"]}).json()[
        "qualified_at"
    ]

    junked = client.post(f"{url}/move", headers=head, json={"to": _junk(board)["id"]})
    back = client.post(f"{url}/move", headers=head, json={"to": working["id"]})

    assert junked.json()["qualified_at"] is None
    assert back.json()["closed_at"] is None
    assert back.json()["qualified_at"] is not None


def test_a_card_won_can_be_called_unqualified_and_won_again(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    url = f"{CRM}/cards/{card}"
    client.post(f"{url}/win", headers=head, json={"amount": "150"})

    junked = client.post(f"{url}/move", headers=head, json={"to": _junk(board)["id"]})
    won = client.post(f"{url}/win", headers=head, json={"amount": "90"})

    assert junked.json()["won_amount_minor"] is None
    assert junked.json()["closed_at"] is not None
    assert won.status_code == 200
    assert won.json()["won_amount_minor"] == 9000


def test_settings_say_since_when_the_crm_runs(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    _running(client, head)

    settings = client.get(f"{CRM}/settings", headers=head).json()

    assert settings["setup"]["enabled_at"] is not None


def test_the_migration_gives_every_board_the_column_once(
    client: TestClient, db: Session
) -> None:
    from importlib import import_module

    from sqlalchemy import text

    from app.modules.crm.models import CrmStage

    head = _auth(_owner(db))
    _running(client, head)
    db.execute(text("DELETE FROM crm_stages WHERE kind = 'junk'"))
    db.commit()
    migration = import_module("migrations.versions.20261102_0013_crm_junk_stage")

    db.execute(text(migration.ADD_COLUMN))
    db.execute(text(migration.ADD_COLUMN))
    db.commit()

    stages = sorted(db.query(CrmStage).all(), key=lambda s: s.position)
    assert [s.kind for s in stages][-3:] == ["won", "lost", "junk"]
    assert [s.position for s in stages] == list(range(len(stages)))


def _pixels(db: Session, owner: User, *names: str) -> None:
    from app.modules.integrations.models import PixelAccount

    account = db.query(AdAccount).filter_by(owner_id=owner.id).one()
    for name in names:
        db.add(
            PixelAccount(
                owner_id=owner.id,
                ad_account_id=account.id,
                connection_id=account.connection_id,
                provider=PROVIDER,
                external_id=name,
                name=name,
                is_active=False,
            )
        )
    db.commit()


def test_the_pixel_state_tells_none_from_unselected_from_ready(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    assert _running(client, head)["pixel_state"] == "none"
    _pixels(db, owner, "px_a", "px_b")

    meta = client.get(f"{CRM}/settings", headers=head).json()["meta"]
    assert client.get(CRM, headers=head).json()["pixel_state"] == "unselected"
    assert meta["state"] == "unselected"
    assert meta["selected"] is None
    assert [p["external_id"] for p in meta["pixels"]] == ["px_a", "px_b"]

    chosen = client.post(
        f"{CRM}/settings/pixel", headers=head, json={"external_id": "px_b"}
    )

    assert chosen.status_code == 200
    assert chosen.json()["meta"] | {"pixels": []} == {
        "state": "ready",
        "selected": "px_b",
        "pixels": [],
    }
    assert client.get(CRM, headers=head).json()["pixel_state"] == "ready"


def test_a_pixel_of_another_account_cannot_be_chosen(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)

    answer = client.post(
        f"{CRM}/settings/pixel", headers=head, json={"external_id": "px_foreign"}
    )

    assert answer.json()["code"] == "unknown_account"


def test_a_manager_cannot_choose_the_pixel(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _pixels(db, owner, "px_a")
    _, staff = _member(client, head, "menejer@example.com")
    new = "Yz4$kW8nRt2q"
    client.post(f"{CRM}/password", headers=staff, json={"password": new, "again": new})

    answer = client.post(
        f"{CRM}/settings/pixel", headers=staff, json={"external_id": "px_a"}
    )

    assert answer.status_code == 404


def test_reading_pixels_again_finds_a_new_one(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.crm import routers

    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)

    def found(session: Session, *, ad_account_id: object) -> str:
        _pixels(session, owner, "px_new")
        return "1"

    monkeypatch.setattr(routers, "sync_pixels", found)
    monkeypatch.setattr(routers.throttle, "hit", lambda **_: True)

    answer = client.post(f"{CRM}/settings/pixel/refresh", headers=head)

    assert answer.status_code == 200
    assert answer.json()["meta"]["pixels"][0]["external_id"] == "px_new"


def test_a_failed_read_says_so(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.crm import routers

    head = _auth(_owner(db))
    _running(client, head)
    monkeypatch.setattr(routers, "sync_pixels", lambda *_, **__: "unusable")
    monkeypatch.setattr(routers.throttle, "hit", lambda **_: True)

    answer = client.post(f"{CRM}/settings/pixel/refresh", headers=head)

    assert answer.status_code == 400
    assert answer.json()["code"] == "pixels_unread"


def test_reading_pixels_again_is_limited(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.crm import routers

    head = _auth(_owner(db))
    _running(client, head)
    monkeypatch.setattr(routers.throttle, "hit", lambda **_: False)

    answer = client.post(f"{CRM}/settings/pixel/refresh", headers=head)

    assert answer.status_code == 429


def test_no_pixel_can_be_chosen_on_the_connections_screen(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _pixels(db, owner, "px_a")
    picked = client.post(
        "/api/v1/connections/meta/pixel", headers=head, json={"external_id": "px_a"}
    )
    assert picked.status_code == 200

    cleared = client.post(
        "/api/v1/connections/meta/pixel", headers=head, json={"external_id": ""}
    )

    assert cleared.status_code == 200
    assert client.get(CRM, headers=head).json().get("pixel_state") in (
        None,
        "unselected",
    )


def _no_rehearsal(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.crm import routers
    from app.modules.integrations.services import sync

    monkeypatch.setattr(sync.settings, "ads_dry_run", False)
    monkeypatch.setattr(sync, "_usable_token", lambda _: "token")
    monkeypatch.setattr(routers.throttle, "hit", lambda **_: True)


def test_a_pixel_made_here_is_chosen_and_named_after_the_page(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.integrations.services import sync

    _no_rehearsal(monkeypatch)
    asked: dict[str, Any] = {}

    def made(**kwargs: Any) -> str:
        asked.update(kwargs)
        return "px_made"

    monkeypatch.setattr(sync, "make_pixel", made)
    head = _auth(_owner(db))
    _running(client, head)

    answer = client.post(f"{CRM}/settings/pixel/create", headers=head)

    assert answer.status_code == 200
    assert answer.json()["meta"]["state"] == "ready"
    assert answer.json()["meta"]["selected"] == "px_made"
    assert (asked["account_id"], asked["name"]) == ("act_1", "Sahifa CRM")
    assert asked["dry_run"] is False
    assert client.get(CRM, headers=head).json()["pixel_state"] == "ready"


def test_a_second_pixel_is_made_in_the_portfolio_and_chosen(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from metaads.errors import MetaAPIError

    from app.modules.integrations.services import sync

    _no_rehearsal(monkeypatch)
    owner = _owner(db)
    _pixels(db, owner, "px_old")
    db.execute(
        update(AdAccount)
        .where(AdAccount.owner_id == owner.id)
        .values(business_external_id="b1")
    )
    db.commit()
    asked: dict[str, Any] = {}

    def refused(**_: Any) -> str:
        raise MetaAPIError("one only", code=6200)

    def made(**kwargs: Any) -> str:
        asked.update(kwargs)
        return "px_new"

    monkeypatch.setattr(sync, "make_pixel", refused)
    monkeypatch.setattr(sync, "make_business_pixel", made)
    head = _auth(owner)
    _running(client, head)
    client.post(f"{CRM}/settings/pixel", headers=head, json={"external_id": "px_old"})

    answer = client.post(f"{CRM}/settings/pixel/create", headers=head)

    assert answer.status_code == 200
    assert answer.json()["meta"]["selected"] == "px_new"
    assert {p["external_id"] for p in answer.json()["meta"]["pixels"]} == {
        "px_old",
        "px_new",
    }
    assert (asked["business_id"], asked["account_id"]) == ("b1", "act_1")


def test_a_rehearsal_makes_no_pixel(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.crm import routers
    from app.modules.integrations.services import sync

    monkeypatch.setattr(sync.settings, "ads_dry_run", True)
    monkeypatch.setattr(routers.throttle, "hit", lambda **_: True)
    head = _auth(_owner(db))
    _running(client, head)

    answer = client.post(f"{CRM}/settings/pixel/create", headers=head)

    assert answer.json()["code"] == "pixel_rehearsed"


@pytest.mark.parametrize(
    ("meta_code", "ours"),
    [
        (6200, "pixel_already_there"),
        (6202, "pixel_already_there"),
        (200, "pixel_not_allowed"),
        (100, "pixel_not_created"),
    ],
)
def test_metas_refusal_reads_in_plain_words(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    meta_code: int,
    ours: str,
) -> None:
    from metaads.errors import MetaAPIError

    from app.modules.integrations.services import sync

    _no_rehearsal(monkeypatch)

    def refused(**_: Any) -> str:
        raise MetaAPIError("no", code=meta_code)

    monkeypatch.setattr(sync, "make_pixel", refused)
    monkeypatch.setattr(sync, "sync_pixels", lambda *_, **__: "1")
    head = _auth(_owner(db))
    _running(client, head)

    answer = client.post(f"{CRM}/settings/pixel/create", headers=head)

    assert answer.status_code == 400
    assert answer.json()["code"] == ours


def test_a_manager_cannot_make_a_pixel(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _, staff = _member(client, head, "menejer@example.com")
    new = "Yz4$kW8nRt2q"
    client.post(f"{CRM}/password", headers=staff, json={"password": new, "again": new})

    answer = client.post(f"{CRM}/settings/pixel/create", headers=staff)

    assert answer.status_code == 404


def test_the_board_reads_leads_once_not_once_per_card(
    client: TestClient, db: Session
) -> None:
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    head = _auth(_owner(db))
    board = _running(client, head)
    column = board["columns"][0]
    assert len(column["cards"]) == 3
    seen: list[str] = []

    def _record(*args: Any) -> None:
        seen.append(" ".join(str(args[2]).split()))

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        again = client.get(CRM, headers=head).json()
        page = client.get(f"{CRM}/columns/{column['stage']['id']}", headers=head)
    finally:
        event.remove(Engine, "before_cursor_execute", _record)

    assert page.status_code == 200, page.text
    assert [c["lead"]["full_name"] for c in again["columns"][0]["cards"]] == [
        c["lead"]["full_name"] for c in column["cards"]
    ]
    assert {c["lead"]["ad_external_id"] for c in page.json()["cards"]} == {"ad_1"}
    lead_reads = [sql for sql in seen if sql.startswith("SELECT leads.id")]
    assert len(lead_reads) == 2, lead_reads


def test_an_opened_lead_says_where_it_stands_on_the_board_as_the_list_does(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    _running(client, head)

    rows = client.get("/api/v1/leads", headers=head).json()["rows"]
    placed = next(row for row in rows if row["place"])

    one = client.get(f"/api/v1/leads/{placed['id']}", headers=head)

    assert one.status_code == 200
    assert one.json()["place"] == placed["place"]


def _total(board: dict[str, Any]) -> int:
    return sum(column["total"] for column in board["columns"])


def test_a_phone_is_found_however_it_is_typed_and_a_wildcard_is_a_letter(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    assert _total(_running(client, head)) == 3

    def found(q: str) -> int:
        return _total(client.get(CRM, headers=head, params={"q": q}).json())

    assert found("90 000 00 01") == 1
    assert found("90-000-00-01") == 1
    assert found("+998 (90) 000-00-02") == 1
    assert found("lid1") == 1
    # A name with a figure in it is not a phone: «lid 9» is nobody here.
    assert found("lid 9") == 0
    assert found("_") == 0
    assert found("%") == 0


def test_the_chips_count_under_the_search_they_stand_beside(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    for card in board["columns"][0]["cards"]:
        due = client.post(
            f"{CRM}/cards/{card['id']}/due", headers=head, json={"due": LATER}
        )
        assert due.is_success
    db.execute(update(CrmCard).values(due_at=utcnow() - timedelta(hours=1)))
    db.commit()

    assert client.get(CRM, headers=head).json()["late"] == 3
    narrowed = client.get(CRM, headers=head, params={"q": "lid1"}).json()
    assert narrowed["late"] == 1
    pressed = client.get(CRM, headers=head, params={"q": "lid1", "f": "late"}).json()
    assert (pressed["late"], _total(pressed)) == (1, 1)


def test_the_leads_of_no_advert_can_be_listed_and_downloaded(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    one = db.query(Lead).filter_by(owner_id=owner.id, leadgen_id="lid0").one()
    one.ad_external_id = ""
    db.commit()

    rows = client.get("/api/v1/leads", headers=head, params={"ad": "none"}).json()
    file = client.get("/api/v1/leads/export", headers=head, params={"ad": "none"})

    assert [row["full_name"] for row in rows["rows"]] == ["lid0"]
    assert file.status_code == 200
    wild = client.get("/api/v1/leads", headers=head, params={"q": "_"}).json()
    assert wild["rows"] == []


def _asks_again(db: Session, owner: User, was: str, name: str) -> str:
    """The telephone of lead ``was`` sends a new enquiry now; the CRM places it."""
    from app.modules.crm import services

    old = db.query(Lead).filter_by(owner_id=owner.id, leadgen_id=was).one()
    now = utcnow()
    again = Lead(
        owner_id=owner.id,
        provider=PROVIDER,
        leadgen_id=name,
        form_id=old.form_id,
        campaign_external_id=old.campaign_external_id,
        ad_external_id=old.ad_external_id,
        phone_e164=old.phone_e164,
        full_name=name,
        submitted_at=now,
        received_at=now,
    )
    db.add(again)
    db.commit()
    return services.place_lead(db, lead_id=str(again.id))


def _card_named(board: dict[str, Any], name: str) -> tuple[dict[str, Any], str]:
    for column in board["columns"]:
        for card in column["cards"]:
            if card["lead"]["full_name"] == name:
                return card, column["stage"]["kind"]
    raise AssertionError(name)


def test_a_sold_customer_who_asks_again_keeps_the_sale_and_gets_a_new_card(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    sold, _ = _card_named(board, "lid0")
    won = client.post(
        f"{CRM}/cards/{sold['id']}/win", headers=head, json={"amount": "150"}
    )
    assert won.is_success

    assert _asks_again(db, owner, "lid0", "yana") == "returned"

    board = client.get(CRM, headers=head).json()
    kept, where = _card_named(board, "lid0")
    assert (kept["id"], where) == (sold["id"], "won")
    assert (
        next(c for c in board["columns"] if c["stage"]["kind"] == "won")["won_minor"]
        == won.json()["won_amount_minor"]
    )
    new, where = _card_named(board, "yana")
    assert where == "new"
    assert new["id"] != sold["id"]
    assert new["returned"] == 1
    # The newest enquiry stands first in its column.
    assert board["columns"][0]["cards"][0]["id"] == new["id"]
    assert _total(board) == 4


def test_a_refused_customer_who_asks_again_returns_on_top_of_the_first_column(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    card, _ = _card_named(board, "lid1")
    reason = client.get(f"{CRM}/settings", headers=head).json()["reasons"][0]["id"]
    lost = client.post(
        f"{CRM}/cards/{card['id']}/lose", headers=head, json={"reason": reason}
    )
    assert lost.is_success

    assert _asks_again(db, owner, "lid1", "qaytdi") == "returned"

    board = client.get(CRM, headers=head).json()
    back, where = _card_named(board, "qaytdi")
    assert (back["id"], where, back["returned"]) == (card["id"], "new", 1)
    assert board["columns"][0]["cards"][0]["id"] == card["id"]
    assert _total(board) == 3


def test_the_untaken_chip_counts_the_new_cards_nobody_holds(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    assert board["untaken"] == 3
    card = board["columns"][0]["cards"][0]["id"]
    assert client.post(f"{CRM}/cards/{card}/take", headers=head).is_success

    after = client.get(CRM, headers=head, params={"f": "untaken"}).json()

    assert (after["untaken"], _total(after)) == (2, 2)
    assert card not in [c["id"] for c in after["columns"][0]["cards"]]


def test_a_file_of_seven_days_holds_seven_days(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    head = _auth(owner)
    db.execute(
        update(Lead)
        .where(Lead.owner_id == owner.id)
        .values(submitted_at=utcnow() - timedelta(days=20))
    )
    db.commit()

    def file(**params: Any) -> int:
        answer = client.get("/api/v1/leads/export", headers=head, params=params)
        return answer.status_code

    assert file() == 200
    assert file(days=30) == 200
    # Nothing came in the last week, so there is nothing to download.
    assert file(days=7) == 404


def test_the_leads_list_offers_the_crm_only_where_this_pair_runs_one(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    assert client.get("/api/v1/leads", headers=head).json()["crm_on"] is False

    _running(client, head)

    assert client.get("/api/v1/leads", headers=head).json()["crm_on"] is True


def test_when_the_owner_hands_cards_out_a_manager_sees_and_takes_only_their_own(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    member, signed_in = _member(client, head, "qol@example.com")
    client.post(
        f"{CRM}/password",
        headers=signed_in,
        json={"password": PASSWORD + "1", "again": PASSWORD + "1"},
    )
    first, second = (card["id"] for card in board["columns"][0]["cards"][:2])
    given = client.post(
        f"{CRM}/cards/{first}/assign",
        headers=head,
        json={"assignee": member["user"]["id"]},
    )
    assert given.is_success

    seen = client.get(CRM, headers=signed_in).json()

    assert (seen["untaken"], _total(seen)) == (0, 1)
    assert client.post(f"{CRM}/cards/{second}/take", headers=signed_in).status_code in (
        403,
        404,
    )
    assert client.get(CRM, headers=head).json()["untaken"] == 2


def test_the_statistics_count_one_cohort_the_leads_that_came_in_the_period(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    sold, _ = _card_named(board, "lid0")
    refused, _ = _card_named(board, "lid1")
    reason = client.get(f"{CRM}/settings", headers=head).json()["reasons"][0]
    assert client.post(f"{CRM}/cards/{sold['id']}/take", headers=head).is_success
    assert client.post(
        f"{CRM}/cards/{sold['id']}/win", headers=head, json={"amount": "150"}
    ).is_success
    assert client.post(
        f"{CRM}/cards/{refused['id']}/lose", headers=head, json={"reason": reason["id"]}
    ).is_success

    stats = client.get(f"{CRM}/stats", headers=head, params={"period": "7"}).json()

    totals = stats["totals"]
    assert stats["state"] == "on"
    assert (stats["range"]["days"], len(stats["daily"]["days"])) == (7, 7)
    assert (totals["leads"], totals["won"], totals["lost"]) == (3, 1, 1)
    assert (totals["taken"], totals["open"]) == (1, 1)
    assert totals["conversion_pct"] == 33.3
    assert totals["revenue_minor"] == totals["avg_deal_minor"] > 0
    # Taken two hours after the enquiry came.
    assert 115 <= totals["first_response_min"] <= 125
    assert sum(stats["daily"]["leads"]) == 3
    assert sum(stats["daily"]["won"]) == 1
    funnel = {row["stage"]["kind"]: row["count"] for row in stats["funnel"]}
    assert (funnel["new"], funnel["won"], funnel["lost"]) == (3, 1, 1)
    # Every working column was passed by the sold card.
    assert {
        row["count"] for row in stats["funnel"] if row["stage"]["kind"] == "open"
    } == {1}
    assert stats["reasons"] == [{"name": reason["name"], "count": 1, "pct": 100}]
    assert [(ad["id"], ad["leads"], ad["won"]) for ad in stats["ads"]] == [
        ("ad_1", 3, 1)
    ]
    # The owner holds both cards they closed: the sold one and the refused one.
    assert [(m["leads"], m["won"]) for m in stats["managers"]] == [(2, 1)]

    # Leads that came before the days asked for are not this period's.
    db.execute(
        update(Lead)
        .where(Lead.owner_id == owner.id)
        .values(submitted_at=utcnow() - timedelta(days=10))
    )
    db.commit()
    week = client.get(f"{CRM}/stats", headers=head, params={"period": "7"}).json()
    month = client.get(f"{CRM}/stats", headers=head, params={"period": "30"}).json()
    assert (week["totals"]["leads"], week["totals"]["won"]) == (0, 0)
    assert week["totals"]["open"] == 1
    assert month["totals"]["leads"] == 3


def test_a_manager_has_no_statistics(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    _running(client, head)
    _, signed_in = _member(client, head, "stat@example.com")
    client.post(
        f"{CRM}/password",
        headers=signed_in,
        json={"password": PASSWORD + "1", "again": PASSWORD + "1"},
    )

    assert client.get(f"{CRM}/stats", headers=signed_in).status_code == 404


def test_today_is_what_is_still_to_do_and_ends_at_the_readers_midnight(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    cards = [card["id"] for card in board["columns"][0]["cards"]]
    for card in cards:
        assert client.post(
            f"{CRM}/cards/{card}/due", headers=head, json={"due": LATER}
        ).is_success
    now = utcnow()

    def due(card: str, at: Any) -> None:
        db.execute(update(CrmCard).where(CrmCard.id == card).values(due_at=at))

    due(cards[0], now - timedelta(minutes=5))
    due(cards[1], now + timedelta(minutes=5))
    due(cards[2], now + timedelta(hours=30))
    db.commit()

    # Kiritimati is 14 hours ahead and Pago Pago 11 behind: five minutes from
    # now is today on any clock, thirty hours from now on none.
    for zone in ("", "Pacific/Kiritimati", "Pacific/Pago_Pago", "No/Such_Zone"):
        seen = client.get(CRM, headers=head, params={"tz": zone}).json()
        assert seen["late"] == 1, zone
        assert seen["today"] in (0, 1), zone
    pressed = client.get(CRM, headers=head, params={"f": "today"}).json()
    assert _total(pressed) == pressed["today"]
    file = client.get(
        "/api/v1/leads/export", headers=head, params={"tz": "Pacific/Kiritimati"}
    )
    assert file.status_code == 200
