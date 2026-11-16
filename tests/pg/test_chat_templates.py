"""«Xabar yozishsin» templates: a greeting and its questions kept under a name."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.deletion import delete_rows
from app.modules.ads.models import CampaignLaunch, ChatTemplate
from app.modules.ads.services import chat_templates
from app.modules.integrations.models import PageAccount
from tests.pg.conftest import sign_up
from tests.pg.test_launch_drafts import _opened

BODY = {
    "name": "Yozgi aksiya",
    "welcomeText": "  Salom! Yozing.  ",
    "chatQuestions": [
        "Narxi qancha?",
        " narxi  qancha? ",
        "",
        "Yetkazib berish bormi?",
    ],
    "chatAnswers": [" 100 ming so'm ", "boshqa", "yo'q", ""],
}


def _path(draft_id: str) -> str:
    return f"/api/v1/launch/drafts/{draft_id}/chat-templates"


def test_a_template_is_saved_listed_written_over_and_deleted(
    client: TestClient, db: Session
) -> None:
    auth, draft_id = _opened(client, db)
    path = _path(draft_id)
    empty = client.get(path, headers=auth)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"items": [], "maxItems": 20, "maxNameChars": 40}

    saved = client.post(path, json=BODY, headers=auth)
    assert saved.status_code == 200, saved.text
    (item,) = saved.json()["items"]
    assert item["name"] == "Yozgi aksiya"
    assert item["welcomeText"] == "Salom! Yozing."
    assert item["chatQuestions"] == ["Narxi qancha?", "Yetkazib berish bormi?"]
    # Each answer stays beside its own question when rows are dropped.
    assert item["chatAnswers"] == ["100 ming so'm", ""]

    # The same name in another letter case writes over, it does not add.
    over = client.post(
        path,
        json={"name": " yozgi  AKSIYA ", "welcomeText": "Assalomu alaykum!"},
        headers=auth,
    )
    assert over.status_code == 200, over.text
    (item2,) = over.json()["items"]
    assert item2["id"] == item["id"]
    assert item2["name"] == "yozgi AKSIYA"
    assert item2["welcomeText"] == "Assalomu alaykum!"
    assert item2["chatQuestions"] == [] and item2["chatAnswers"] == []

    second = client.post(path, json=BODY | {"name": "Ikkinchi"}, headers=auth)
    assert [row["name"] for row in second.json()["items"]] == [
        "Ikkinchi",
        "yozgi AKSIYA",
    ]

    gone = client.delete(f"{path}/{item['id']}", headers=auth)
    assert gone.status_code == 200, gone.text
    assert [row["name"] for row in gone.json()["items"]] == ["Ikkinchi"]
    again = client.delete(f"{path}/{item['id']}", headers=auth)
    assert again.status_code == 404, again.text


def test_a_template_is_refused_field_by_field(client: TestClient, db: Session) -> None:
    auth, draft_id = _opened(client, db)
    path = _path(draft_id)

    blank = client.post(path, json={"name": "  ", "welcomeText": ""}, headers=auth)
    assert blank.status_code == 422, blank.text
    assert set(blank.json()["problems"]) == {"name", "welcomeText"}

    long = client.post(
        path,
        json={
            "name": "n" * 41,
            "welcomeText": "s" * 301,
            "chatQuestions": ["q" * 81],
            "chatAnswers": ["a" * 301],
        },
        headers=auth,
    )
    assert long.status_code == 422, long.text
    assert set(long.json()["problems"]) == {
        "name",
        "welcomeText",
        "chatQuestions",
        "chatAnswers",
    }

    many = client.post(
        path,
        json={
            "name": "Ko'p",
            "welcomeText": "Salom",
            "chatQuestions": [f"Savol {n}?" for n in range(5)],
        },
        headers=auth,
    )
    assert many.status_code == 422, many.text
    assert set(many.json()["problems"]) == {"chatQuestions"}
    assert db.scalar(select(ChatTemplate)) is None


def test_no_more_than_the_limit_is_kept_but_a_kept_name_still_saves(
    client: TestClient, db: Session
) -> None:
    auth, draft_id = _opened(client, db)
    path = _path(draft_id)
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    for n in range(chat_templates.MAX_TEMPLATES):
        db.add(
            ChatTemplate(
                owner_id=launch.owner_id,
                page_id=launch.page_id,
                name=f"Shablon {n}",
                welcome_text="Salom",
            )
        )
    db.commit()

    full = client.post(path, json=BODY, headers=auth)
    assert full.status_code == 422, full.text
    assert set(full.json()["problems"]) == {"name"}

    over = client.post(path, json=BODY | {"name": "shablon 3"}, headers=auth)
    assert over.status_code == 200, over.text
    assert len(over.json()["items"]) == chat_templates.MAX_TEMPLATES


def test_templates_stay_with_their_owner_and_page(
    client: TestClient, db: Session
) -> None:
    auth, draft_id = _opened(client, db)
    path = _path(draft_id)
    saved = client.post(path, json=BODY, headers=auth).json()["items"][0]
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None and launch.page_id is not None

    # Another page of the same owner has its own list.
    page = db.get(PageAccount, launch.page_id)
    assert page is not None
    other = PageAccount(
        owner_id=page.owner_id,
        connection_id=page.connection_id,
        provider=page.provider,
        external_id="page_2",
        name="Boshqa",
        token_encrypted=b"x",
    )
    db.add(other)
    db.flush()
    db.add(
        ChatTemplate(
            owner_id=launch.owner_id,
            page_id=other.id,
            name="Boshqa sahifa",
            welcome_text="Salom",
        )
    )
    db.commit()
    assert [row["name"] for row in client.get(path, headers=auth).json()["items"]] == [
        "Yozgi aksiya"
    ]

    # A stranger reads, saves and deletes nothing here.
    stranger = sign_up(client, email="boshqa@example.com", phone="+998901112244")
    assert client.get(path, headers=stranger).status_code == 404
    assert client.post(path, json=BODY, headers=stranger).status_code == 404
    assert client.delete(f"{path}/{saved['id']}", headers=stranger).status_code == 404
    assert client.get(path).status_code == 401

    # A page that goes takes its templates with it.
    delete_rows(db, PageAccount.__table__, PageAccount.id == other.id)
    db.commit()
    assert db.scalar(select(ChatTemplate.name)) == "Yozgi aksiya"


# --- The copy kept on the page for Ads Manager ------------------------------
class _Meta:
    """Stands in for metaads.welcome_flows: records, refuses on demand."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.refuse_update = False
        self.refuse_create: Exception | None = None

    def create(self, **fields: object) -> str:
        self.calls.append(("create", fields))
        if self.refuse_create is not None:
            raise self.refuse_create
        return f"flow-{len(self.calls)}"

    def update(self, **fields: object) -> None:
        self.calls.append(("update", fields))
        if self.refuse_update:
            from metaads.errors import MetaAPIError

            raise MetaAPIError("used in an ad", code=100)

    def delete(self, **fields: object) -> None:
        self.calls.append(("delete", fields))


def _meta(monkeypatch, *, on: bool = True) -> _Meta:  # type: ignore[no-untyped-def]
    from cryptography.fernet import Fernet

    from app.common.config import settings
    from app.modules.ads.services import chat_template_flows

    fake = _Meta()
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "meta_ask_messaging", on)
    monkeypatch.setattr(chat_template_flows, "create_flow", fake.create)
    monkeypatch.setattr(chat_template_flows, "update_flow", fake.update)
    monkeypatch.setattr(chat_template_flows, "delete_flow", fake.delete)
    return fake


def _scopes(db: Session, draft_id: str, scopes: list[str]) -> None:
    """The connection's grants, and a page token that opens."""
    from app.common.crypto import encrypt
    from app.modules.integrations.models import ProviderConnection

    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    for page in db.scalars(
        select(PageAccount).where(PageAccount.owner_id == launch.owner_id)
    ):
        page.token_encrypted = encrypt("page-token")
    for connection in db.scalars(
        select(ProviderConnection).where(ProviderConnection.owner_id == launch.owner_id)
    ):
        connection.scopes = scopes
    db.commit()


def test_with_the_setting_off_nothing_goes_to_meta(
    client: TestClient, db: Session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    fake = _meta(monkeypatch, on=False)
    auth, draft_id = _opened(client, db)

    saved = client.post(_path(draft_id), json=BODY, headers=auth)

    assert saved.status_code == 200, saved.text
    assert saved.json()["items"][0]["meta"] == "off"
    assert fake.calls == []


def test_a_saved_template_is_kept_on_the_page_rewritten_and_taken_off(
    client: TestClient, db: Session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    fake = _meta(monkeypatch)
    auth, draft_id = _opened(client, db)
    _scopes(db, draft_id, ["ads_management", "pages_messaging"])
    path = _path(draft_id)

    saved = client.post(path, json=BODY, headers=auth)
    assert saved.status_code == 200, saved.text
    (item,) = saved.json()["items"]
    assert item["meta"] == "saved"
    kind, fields = fake.calls[-1]
    assert kind == "create"
    assert fields["name"] == "Yozgi aksiya"
    assert fields["text"] == "Salom! Yozing."
    assert fields["questions"] == ("Narxi qancha?", "Yetkazib berish bormi?")
    # Instagram only with instagram_manage_messages.
    assert fields["platforms"] == ("messenger",)
    row = db.get(ChatTemplate, uuid.UUID(item["id"]))
    assert row is not None
    db.refresh(row)
    assert row.meta_flow_id == "flow-1"

    # The same name again rewrites the flow it already has.
    client.post(path, json=BODY | {"welcomeText": "Yangi salom"}, headers=auth)
    kind, fields = fake.calls[-1]
    assert kind == "update" and fields["flow_id"] == "flow-1"
    assert fields["text"] == "Yangi salom"

    # A flow an advert uses is kept by Meta: a new one is made instead.
    fake.refuse_update = True
    again = client.post(path, json=BODY | {"welcomeText": "Uchinchi"}, headers=auth)
    assert again.json()["items"][0]["meta"] == "saved"
    assert [kind for kind, _ in fake.calls[-2:]] == ["update", "create"]
    db.refresh(row)
    assert row.meta_flow_id == "flow-4"

    gone = client.delete(f"{path}/{item['id']}", headers=auth)
    assert gone.status_code == 200, gone.text
    kind, fields = fake.calls[-1]
    assert kind == "delete" and fields["flow_id"] == "flow-4"


def test_without_pages_messaging_the_template_is_saved_here_only(
    client: TestClient, db: Session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    fake = _meta(monkeypatch)
    auth, draft_id = _opened(client, db)
    _scopes(db, draft_id, ["ads_management", "pages_manage_ads"])

    saved = client.post(_path(draft_id), json=BODY, headers=auth)

    assert saved.status_code == 200, saved.text
    assert saved.json()["items"][0]["meta"] == "no_permission"
    assert fake.calls == []


def test_a_refusal_from_meta_never_undoes_the_save(
    client: TestClient, db: Session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from metaads.errors import MetaAPIError

    fake = _meta(monkeypatch)
    auth, draft_id = _opened(client, db)
    _scopes(db, draft_id, ["pages_messaging"])

    fake.refuse_create = MetaAPIError("(#200) requires pages_messaging", code=200)
    denied = client.post(_path(draft_id), json=BODY, headers=auth)
    assert denied.status_code == 200, denied.text
    assert denied.json()["items"][0]["meta"] == "no_permission"

    fake.refuse_create = MetaAPIError("Invalid parameter", code=100)
    failed = client.post(_path(draft_id), json=BODY, headers=auth)
    assert failed.status_code == 200, failed.text
    assert failed.json()["items"][0]["meta"] == "failed"
    assert failed.json()["items"][0]["welcomeText"] == "Salom! Yozing."
