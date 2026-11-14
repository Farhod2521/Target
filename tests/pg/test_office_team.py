"""Jamoa and the staff bot's screen: who may do what, and what each refusal says."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.services import creation
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.backoffice.permissions import has_role, roles_of
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    ProviderConnection,
)
from app.modules.notifications import selectors as chats
from app.modules.notifications.models import StaffChat
from app.modules.notifications.services import (
    dev_alerts,
    handle_staff_update,
    report_launch_failure,
)
from tests.pg.test_office_actions import _bearer, _shop, _staff
from tests.pg.test_office_telegram import FakeBot, _text, fake  # noqa: F401

TEAM = "/api/v1/office/team"
BOT = "/api/v1/office/telegram"


def _kinds(db: Session, member: User) -> list[str]:
    return list(
        db.scalars(
            select(StaffAction.kind)
            .where(StaffAction.owner_id == member.id)
            .order_by(StaffAction.created_at)
        )
    )


def test_only_the_owner_reads_and_writes_the_team(
    client: TestClient, db: Session
) -> None:
    _, finance = _staff(db, Role.FINANCE, email="f@x.co")
    colleague, _ = _staff(db, Role.SUPPORT, email="s@x.co")
    customer, _ = _shop(db)
    for call in (
        client.get(TEAM, headers=finance),
        client.get(TEAM, headers=_bearer(customer)),
        client.post(TEAM, headers=finance, json={"email": customer.email}),
        client.post(
            f"{TEAM}/{colleague.id}/roles", headers=finance, json={"roles": ["Owner"]}
        ),
        client.post(f"{TEAM}/{colleague.id}/remove", headers=finance),
    ):
        assert call.status_code == 404
    assert not has_role(db, colleague, (Role.OWNER,))
    db.refresh(colleague)
    assert colleague.is_staff


def test_the_roster_lists_the_staff_with_their_roles(
    client: TestClient, db: Session
) -> None:
    _, owner = _staff(db, Role.OWNER, email="o@x.co")
    _staff(db, Role.SALES, Role.SALES_LEAD, email="b@x.co")
    _staff(db, email="root@x.co", superuser=True)
    _staff(db, email="none@x.co")
    _shop(db)

    rows = client.get(TEAM, headers=owner).json()["members"]

    assert [row["email"] for row in rows] == [
        "root@x.co",
        "b@x.co",
        "none@x.co",
        "o@x.co",
    ]
    assert rows[0]["roles"] == [str(role) for role in Role]
    assert rows[1]["roles"] == ["Sales", "SalesLead"]
    assert rows[2]["roles"] == []
    assert [row["is_me"] for row in rows] == [False, False, False, True]


def test_roles_are_replaced_whole_and_journalled(
    client: TestClient, db: Session
) -> None:
    owner, headers = _staff(db, Role.OWNER, email="o@x.co")
    member, _ = _staff(db, Role.SUPPORT, Role.FINANCE, email="m@x.co")
    outsider = Group(name="Beta")
    db.add(outsider)
    db.flush()
    db.add(UserGroup(user_id=member.id, group_id=outsider.id))
    db.commit()

    done = client.post(
        f"{TEAM}/{member.id}/roles",
        headers=headers,
        json={"roles": ["Finance", "Engineer"]},
    )

    assert done.status_code == 200
    assert done.json()["roles"] == ["Engineer", "Finance"]
    db.expire_all()
    assert roles_of(db, member) == {"Engineer", "Finance"}
    held = db.scalars(
        select(Group.name)
        .join(UserGroup, UserGroup.group_id == Group.id)
        .where(UserGroup.user_id == member.id)
    )
    assert "Beta" in set(held)
    trace = db.scalar(select(StaffAction).where(StaffAction.owner_id == member.id))
    assert trace is not None
    assert trace.kind == ActionKind.ROLES_CHANGED
    assert trace.actor_id == owner.id
    assert trace.detail == {
        "from": ["Finance", "Support"],
        "to": ["Engineer", "Finance"],
    }


def test_a_role_nobody_seeded_is_given_all_the_same(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="o@x.co")
    member, _ = _staff(db, email="m@x.co")
    assert db.scalar(select(Group).where(Group.name == "SalesLead")) is None

    client.post(
        f"{TEAM}/{member.id}/roles", headers=headers, json={"roles": ["SalesLead"]}
    )

    db.expire_all()
    assert roles_of(db, member) == {"SalesLead"}


def test_taking_every_role_away_closes_the_office(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="o@x.co")
    member, theirs = _staff(db, Role.SUPPORT, email="m@x.co")
    assert client.get("/api/v1/office/me", headers=theirs).status_code == 200

    client.post(f"{TEAM}/{member.id}/roles", headers=headers, json={"roles": []})

    assert client.get("/api/v1/office/me", headers=theirs).status_code == 404


def test_nobody_edits_themselves_or_a_super_admin(
    client: TestClient, db: Session
) -> None:
    owner, headers = _staff(db, Role.OWNER, email="o@x.co")
    root, root_headers = _staff(db, email="root@x.co", superuser=True)
    for target in (owner, root):
        roles = client.post(
            f"{TEAM}/{target.id}/roles", headers=headers, json={"roles": []}
        )
        gone = client.post(f"{TEAM}/{target.id}/remove", headers=headers)
        assert roles.status_code == gone.status_code == 400
    own = client.post(
        f"{TEAM}/{root.id}/roles", headers=root_headers, json={"roles": []}
    )
    assert "hamkasbdan" in own.json()["detail"]
    db.expire_all()
    assert roles_of(db, owner) == {"Owner"}
    assert root.is_staff and owner.is_staff
    assert not db.scalars(select(StaffAction)).all()


def test_an_unknown_role_or_a_customer_is_refused(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="o@x.co")
    member, _ = _staff(db, email="m@x.co")
    customer, _ = _shop(db)

    bad = client.post(
        f"{TEAM}/{member.id}/roles", headers=headers, json={"roles": ["King"]}
    )
    outside = client.post(
        f"{TEAM}/{customer.id}/roles", headers=headers, json={"roles": ["Owner"]}
    )
    gone = client.post(f"{TEAM}/{customer.id}/remove", headers=headers)

    assert bad.status_code == 422
    assert outside.status_code == gone.status_code == 404
    db.expire_all()
    assert not customer.is_staff


def test_a_customer_joins_with_no_roles_and_leaves_as_a_customer(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="o@x.co")
    customer, _ = _shop(db)

    name, _, domain = customer.email.partition("@")
    added = client.post(
        TEAM, headers=headers, json={"email": f" {name}@{domain.upper()} "}
    )

    assert added.status_code == 200
    assert added.json()["roles"] == []
    db.expire_all()
    assert customer.is_staff and not roles_of(db, customer)
    assert client.get("/api/v1/office/me", headers=_bearer(customer)).status_code == 404

    client.post(
        f"{TEAM}/{customer.id}/roles", headers=headers, json={"roles": ["Support"]}
    )
    gone = client.post(f"{TEAM}/{customer.id}/remove", headers=headers)

    assert gone.status_code == 200
    db.expire_all()
    assert not customer.is_staff
    assert not db.scalars(
        select(UserGroup).where(UserGroup.user_id == customer.id)
    ).all()
    assert _kinds(db, customer) == [
        ActionKind.STAFF_ADDED,
        ActionKind.ROLES_CHANGED,
        ActionKind.STAFF_REMOVED,
    ]


def test_who_cannot_be_added(client: TestClient, db: Session) -> None:
    _, headers = _staff(db, Role.OWNER, email="o@x.co")
    colleague, _ = _staff(db, Role.SUPPORT, email="s@x.co")
    blocked, _ = _shop(db)
    blocked.is_active = False
    db.commit()

    for email, words in (
        ("nobody@x.co", "topilmadi"),
        (colleague.email, "allaqachon"),
        (blocked.email, "bloklangan"),
    ):
        refused = client.post(TEAM, headers=headers, json={"email": email})
        assert refused.status_code == 400
        assert words in refused.json()["detail"]
    db.expire_all()
    assert not blocked.is_staff


def test_the_menu_follows_the_roles(client: TestClient, db: Session) -> None:
    _, owner = _staff(db, Role.OWNER, email="o@x.co")
    _, sales = _staff(db, Role.SALES, email="s@x.co")
    of = lambda who: client.get("/api/v1/office/me", headers=who).json()["sections"]  # noqa: E731

    assert {"team", "tg"} <= set(of(owner))
    assert "tg" in of(sales) and "team" not in of(sales)


def test_the_bot_screen_says_what_this_person_gets(
    client: TestClient,
    db: Session,
    fake: FakeBot,  # noqa: F811
) -> None:
    member, support = _staff(db, Role.SUPPORT, email="s@x.co")
    _, engineer = _staff(db, Role.ENGINEER, email="e@x.co")
    _, finance = _staff(db, Role.FINANCE, email="f@x.co")
    _, root = _staff(db, email="root@x.co", superuser=True)

    read = client.get(BOT, headers=support).json()
    assert read["configured"] and read["username"] == "@office_bot"
    assert read["link"] is None
    assert read["roles"] == ["Support"]
    assert read["topics"] == [{"topic": "support", "roles": ["Support", "Owner"]}]

    topics = lambda who: [  # noqa: E731
        row["topic"] for row in client.get(BOT, headers=who).json()["topics"]
    ]
    assert topics(engineer) == ["faults"]
    assert topics(finance) == []
    assert topics(root) == ["support", "faults"]

    db.add(
        StaffChat(
            owner_id=member.id,
            chat_id="700",
            username="anvar",
            is_active=True,
            linked_at=utcnow(),
        )
    )
    db.commit()
    assert client.get(BOT, headers=support).json()["link"]["account"] == "@anvar"


def test_link_then_start_then_unlink(
    client: TestClient,
    db: Session,
    fake: FakeBot,  # noqa: F811
) -> None:
    member, headers = _staff(db, Role.SUPPORT, email="s@x.co")

    url = client.post(f"{BOT}/link", headers=headers).json()["url"]
    assert url.startswith("https://t.me/office_bot?start=")
    code = url.split("start=")[1]

    handle_staff_update(db, payload=_text("700", f"/start {code}"), now=utcnow())

    link = client.get(BOT, headers=headers).json()["link"]
    assert link["account"] == "@u"
    assert client.post(f"{BOT}/unlink", headers=headers).status_code == 200
    assert client.get(BOT, headers=headers).json()["link"] is None
    again = client.post(f"{BOT}/unlink", headers=headers)
    assert again.status_code == 400
    assert member.is_staff


def test_a_bot_with_no_token_says_so(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.common.config import settings

    monkeypatch.setattr(settings, "staff_bot_token", "")
    _, headers = _staff(db, Role.SUPPORT, email="s@x.co")

    assert client.get(BOT, headers=headers).json()["configured"] is False
    refused = client.post(f"{BOT}/link", headers=headers)
    assert refused.status_code == 400
    assert "sozlanmagan" in refused.json()["detail"]


def test_a_customer_cannot_reach_the_bot_screen(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    for call in (
        client.get(BOT, headers=_bearer(customer)),
        client.post(f"{BOT}/link", headers=_bearer(customer)),
        client.post(f"{BOT}/unlink", headers=_bearer(customer)),
    ):
        assert call.status_code == 404


def _failed(db: Session, *, status: str = "failed", **fields: Any) -> CampaignLaunch:
    owner, _ = _shop(db)
    connection = ProviderConnection(
        owner_id=owner.id,
        provider="meta",
        token_encrypted=b"x",
        status="active",
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=owner.id,
        provider="meta",
        external_id="act_1",
        connection_id=connection.id,
        name="Asosiy <kabinet>",
        currency="USD",
    )
    db.add(account)
    db.flush()
    page = PageAccount(
        owner_id=owner.id,
        provider="meta",
        external_id="p1",
        connection_id=connection.id,
        name="Sahifa",
        token_encrypted=b"x",
    )
    db.add(page)
    db.flush()
    launch = CampaignLaunch(
        owner_id=owner.id,
        ad_account_id=account.id,
        page_id=page.id,
        provider="meta",
        status=status,
        error_code="provider",
        error_message="geo_locations <bad>",
        **fields,
    )
    db.add(launch)
    db.commit()
    return launch


@pytest.fixture
def engineer_chat(
    db: Session,
    fake: FakeBot,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> FakeBot:
    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield fake

    monkeypatch.setattr(dev_alerts, "staff_bot", opened)
    member, _ = _staff(db, Role.ENGINEER, email="e@x.co")
    db.add(
        StaffChat(owner_id=member.id, chat_id="800", is_active=True, linked_at=utcnow())
    )
    other, _ = _staff(db, Role.SUPPORT, email="s@x.co")
    db.add(
        StaffChat(owner_id=other.id, chat_id="801", is_active=True, linked_at=utcnow())
    )
    db.commit()
    return fake


def test_a_failed_launch_reaches_the_developers_once_an_hour(
    db: Session, engineer_chat: FakeBot
) -> None:
    launch = _failed(db, error_detail={"title": "Xato", "message": "Joy noto'g'ri"})

    assert report_launch_failure(db, launch_id=str(launch.id)) == 1
    assert report_launch_failure(db, launch_id=str(launch.id)) == 0

    assert [fields["chat_id"] for _, fields in engineer_chat.calls] == ["800"]
    text = engineer_chat.texts()[0]
    assert "Reklama yaratilmadi" in text
    assert "geo_locations &lt;bad&gt;" in text
    assert "Asosiy &lt;kabinet&gt;" in text
    assert "Xato — Joy noto'g'ri" in text
    assert f"/ofis/mijozlar/{launch.owner_id}/reklama/{launch.id}/" in text


def test_a_trace_file_goes_with_the_report(
    db: Session,
    engineer_chat: FakeBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = _failed(db)
    trace = tmp_path / f"2026_{str(launch.id)[:8]}.md"
    trace.write_text("izoh")
    monkeypatch.setattr(dev_alerts, "launch_trace", lambda *, launch_id: trace)

    report_launch_failure(db, launch_id=str(launch.id))

    assert engineer_chat.calls[-1][0] == "send_document"
    assert engineer_chat.calls[-1][1]["content"] == b"izoh"


def test_a_launch_retried_since_is_not_reported(
    db: Session, engineer_chat: FakeBot
) -> None:
    launch = _failed(db, status="created")

    assert report_launch_failure(db, launch_id=str(launch.id)) == 0
    assert engineer_chat.calls == []


def test_the_failure_hook_queues_the_report(
    queued: list[tuple[str, tuple[object, ...]]],
) -> None:
    from app.common import hooks

    hooks.fire(creation.LAUNCH_FAILED_HOOK, launch_id="abc")

    assert any(
        name.endswith("deliver_launch_failure_task") and args == ("abc",)
        for name, args in queued
    )


def test_someone_taken_off_the_staff_gets_nothing_more(
    client: TestClient, db: Session, engineer_chat: FakeBot
) -> None:
    _, headers = _staff(db, Role.OWNER, email="o@x.co")
    chat = db.scalar(select(StaffChat).where(StaffChat.chat_id == "800"))
    assert chat is not None
    client.post(f"{TEAM}/{chat.owner_id}/remove", headers=headers)
    db.expire_all()

    assert chats.staff_chats_where(db, allowed=lambda user: True) == [
        row for row in db.scalars(select(StaffChat)) if row.chat_id == "801"
    ]
    launch = _failed(db)
    assert report_launch_failure(db, launch_id=str(launch.id)) == 0


def test_only_the_superuser_gives_and_takes_the_owner_role(
    client: TestClient, db: Session
) -> None:
    _, owner = _staff(db, Role.OWNER, email="o@x.co")
    _, boss = _staff(db, email="boss@x.co", superuser=True)
    member, _ = _staff(db, Role.SUPPORT, email="m@x.co")
    other, _ = _staff(db, Role.OWNER, Role.FINANCE, email="o2@x.co")
    customer, _ = _shop(db)

    given = client.post(
        f"{TEAM}/{member.id}/roles", headers=owner, json={"roles": ["Owner"]}
    )
    assert given.status_code == 403
    taken = client.post(
        f"{TEAM}/{other.id}/roles", headers=owner, json={"roles": ["Finance"]}
    )
    assert taken.status_code == 403
    assert client.post(f"{TEAM}/{other.id}/remove", headers=owner).status_code == 403
    joined = client.post(
        TEAM, headers=owner, json={"email": customer.email, "roles": ["Owner"]}
    )
    assert joined.status_code == 403
    db.expire_all()
    assert not customer.is_staff
    # An Owner still changes another Owner's other roles.
    kept = client.post(
        f"{TEAM}/{other.id}/roles", headers=owner, json={"roles": ["Owner", "Sales"]}
    )
    assert kept.status_code == 200

    done = client.post(
        f"{TEAM}/{member.id}/roles", headers=boss, json={"roles": ["Owner"]}
    )
    assert done.status_code == 200 and done.json()["roles"] == ["Owner"]


def test_an_account_is_found_and_joins_with_its_roles(
    client: TestClient, db: Session
) -> None:
    _, owner = _staff(db, Role.OWNER, email="o@x.co")
    _, finance = _staff(db, Role.FINANCE, email="f@x.co")
    customer, _ = _shop(db)
    customer.phone = "+998 90 765 43 21"
    db.commit()

    assert client.get(f"{TEAM}/search?q=765", headers=finance).status_code == 404
    assert client.get(f"{TEAM}/search?q=76", headers=owner).status_code == 422
    found = client.get(f"{TEAM}/search", params={"q": "765 43"}, headers=owner)
    assert found.status_code == 200
    assert [row["id"] for row in found.json()["people"]] == [str(customer.id)]
    # The staff are not offered again.
    again = client.get(f"{TEAM}/search", params={"q": "f@x.co"}, headers=owner)
    assert again.json()["people"] == []

    added = client.post(
        TEAM,
        headers=owner,
        json={"email": customer.email, "roles": ["Renewal", "Sales"]},
    )
    assert added.status_code == 200
    assert added.json()["roles"] == ["Renewal", "Sales"]
    assert added.json()["phone"] == "+998 90 765 43 21"
    db.expire_all()
    assert roles_of(db, customer) == {"Renewal", "Sales"}
