"""The Google Sheets destination against PostgreSQL: connecting through
Google's round trip, making the file, writing leads into it, and the
presses that stop, mend and move it. Google itself is a fake behind
googlekit's transport."""

import base64
import json
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.config import settings
from app.common.crypto import encrypt, fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.audit.models import ActionLog
from app.modules.billing.models import Plan, Subscription
from app.modules.destinations.models import FormSheet, LeadDelivery, SheetLink
from app.modules.destinations.services import (
    check_sheet_link,
    deliver_to_sheet,
    prepare_sheet,
    revoke_sheet_token,
    sweep_sheet_checks,
    sweep_sheets,
)
from app.modules.integrations.models import PageAccount, ProviderConnection
from app.modules.leads.models import Lead, LeadForm

SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE = "https://www.googleapis.com/drive/v3/files/"
TOKEN = "https://oauth2.googleapis.com/token"
REVOKE = "https://oauth2.googleapis.com/revoke"
SPREADSHEET = "application/vnd.google-apps.spreadsheet"
TASKS = "app.modules.destinations.tasks"


class FakeGoogle:
    """Google's token, Sheets and Drive endpoints, as far as the port uses them."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.files: dict[str, dict[str, Any]] = {}
        self.refresh_error = ""
        self.scope = "openid email https://www.googleapis.com/auth/drive.file"
        self.made = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url).split("?")[0]
        if url == TOKEN:
            return self._token(parse_qs(request.content.decode()))
        if url == REVOKE:
            return httpx.Response(200, json={})
        if url == SHEETS:
            return self._create(json.loads(request.content))
        if url.startswith(DRIVE):
            found = self.files.get(url.removeprefix(DRIVE))
            if found is None:
                return httpx.Response(404, json={"error": {"message": "gone"}})
            return httpx.Response(
                200,
                json={
                    "id": url.removeprefix(DRIVE),
                    "mimeType": found.get("mime", SPREADSHEET),
                    "trashed": found.get("trashed", False),
                    "capabilities": {"canEdit": found.get("can_edit", True)},
                },
            )
        rest = url.removeprefix(SHEETS + "/")
        if rest.endswith(":batchUpdate"):
            file_id = rest.removesuffix(":batchUpdate")
            self.files[file_id].setdefault("updates", []).extend(
                json.loads(request.content)["requests"]
            )
            return httpx.Response(200, json={"spreadsheetId": file_id})
        if rest.endswith("/values:batchGetByDataFilter"):
            file_id = rest.removesuffix("/values:batchGetByDataFilter")
            column = [row[0] for row in self.rows(file_id)]
            return httpx.Response(
                200, json={"valueRanges": [{"valueRange": {"values": [column]}}]}
            )
        found = self.files.get(rest)
        if found is None:
            return httpx.Response(404, json={"error": {"message": "not found"}})
        return httpx.Response(200, json=self._sheet(rest))

    def rows(self, file_id: str) -> list[list[Any]]:
        out = []
        for update in self.files[file_id].get("updates", []):
            for row in update.get("appendCells", {}).get("rows", []):
                out.append(
                    [
                        next(iter(cell.get("userEnteredValue", {"": ""}).values()))
                        for cell in row["values"]
                    ]
                )
        return out

    def _token(self, form: dict[str, list[str]]) -> httpx.Response:
        if form["grant_type"] == ["refresh_token"]:
            if self.refresh_error:
                return httpx.Response(400, json={"error": self.refresh_error})
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3599})
        claims = base64.urlsafe_b64encode(
            json.dumps({"email": "egasi@gmail.com", "sub": "1"}).encode()
        ).decode()
        return httpx.Response(
            200,
            json={
                "access_token": "picker-at",
                "refresh_token": "rt-1",
                "expires_in": 3599,
                "scope": self.scope,
                "id_token": f"h.{claims.rstrip('=')}.s",
            },
        )

    def _create(self, body: dict[str, Any]) -> httpx.Response:
        self.made += 1
        file_id = f"sheet-{self.made}"
        self.files[file_id] = {
            "title": body["properties"]["title"],
            "headers": [
                cell["userEnteredValue"]["stringValue"]
                for cell in body["sheets"][0]["data"][0]["rowData"][0]["values"]
            ],
            "tabs": [{"properties": {"sheetId": 0, "title": "t"}}],
        }
        return httpx.Response(200, json=self._sheet(file_id))

    def _sheet(self, file_id: str) -> dict[str, Any]:
        return {
            "spreadsheetId": file_id,
            "spreadsheetUrl": f"https://docs.google.com/{file_id}",
            "sheets": self.files[file_id].get("tabs", []),
        }


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    import googlekit.sheets
    import googlekit.transport

    fake = FakeGoogle()

    def client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(fake.handle))

    monkeypatch.setattr(googlekit.transport, "new_client", client)
    monkeypatch.setattr(googlekit.sheets, "new_client", client)
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "google_oauth_client_id", "cid")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "secret")
    monkeypatch.setattr(settings, "google_picker_api_key", "key")
    monkeypatch.setattr(settings, "google_cloud_project_number", "123")
    return fake


def _auth(user: User) -> dict[str, str]:
    token = tokens.issue(subject=str(user.id), kind="access", now=utcnow())
    return {"Authorization": f"Bearer {token}"}


def _owner(db: Session, *, paid: bool = True) -> tuple[User, LeadForm]:
    now = utcnow()
    owner = User(
        email="sheet@example.com", full_name="Ega", password="!", date_joined=now
    )
    db.add(owner)
    db.flush()
    if paid:
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
    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id="fb-1",
        token_encrypted=b"x",
        token_fingerprint=fingerprint("x"),
    )
    db.add(connection)
    db.flush()
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
    db.add(page)
    db.flush()
    form = LeadForm(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="f_1",
        page_id=page.id,
        name="Ariza",
    )
    db.add(form)
    db.commit()
    return owner, form


def _lead(db: Session, owner: User, form: LeadForm, name: str, **extra: Any) -> Lead:
    now = utcnow()
    row = Lead(
        owner_id=owner.id,
        provider=PROVIDER,
        leadgen_id=name,
        form_id=form.id,
        phone_e164="+998900000001",
        full_name=name,
        submitted_at=now - timedelta(minutes=5),
        received_at=now,
        **extra,
    )
    db.add(row)
    db.commit()
    return row


def _link(db: Session, owner: User) -> SheetLink:
    db.expire_all()
    link = db.scalar(select(SheetLink).where(SheetLink.owner_id == owner.id))
    assert link is not None
    return link


def _connect(
    client: TestClient, headers: dict[str, str], body: dict[str, str]
) -> httpx.Response:
    started = client.post(
        "/api/v1/destinations/google/start", json=body, headers=headers
    )
    assert started.status_code == 200, started.text
    query = parse_qs(urlparse(started.json()["url"]).query)
    assert query["redirect_uri"] == [
        f"{settings.site_url}/api/v1/destinations/google/callback"
    ]
    return client.get(
        "/api/v1/destinations/google/callback",
        params={"state": query["state"][0], "code": "c"},
        follow_redirects=False,
    )


def _active(db: Session, owner: User, **fields: Any) -> SheetLink:
    now = utcnow()
    link = SheetLink(
        owner_id=owner.id,
        status="active",
        token_encrypted=encrypt("rt-1"),
        token_fingerprint=fingerprint("rt-1"),
        spreadsheet_id="sheet-1",
        sheet_id="0",
        spreadsheet_url="https://docs.google.com/sheet-1",
        connected_at=now,
        deliver_from=now - timedelta(hours=1),
        **fields,
    )
    db.add(link)
    db.commit()
    return link


def test_the_button_is_gone_without_a_google_client(
    client: TestClient, db: Session
) -> None:
    owner, _ = _owner(db)

    answer = client.get("/api/v1/destinations/sheet", headers=_auth(owner))

    assert answer.json() == {"enabled": False, "panel": None}


def test_one_file_is_made_and_new_leads_are_written_into_it(
    client: TestClient,
    db: Session,
    google: FakeGoogle,
    queued: list[tuple[str, tuple[object, ...]]],
) -> None:
    owner, form = _owner(db)
    headers = _auth(owner)
    old = _lead(db, owner, form, "eski")
    old.created_at = utcnow() - timedelta(days=1)
    db.commit()

    back = _connect(client, headers, {"mode": "single"})

    assert back.status_code == 307
    landed = urlparse(back.headers["location"])
    assert landed.path == "/app/leads"
    assert parse_qs(landed.query)["message"] == [
        "Google ulandi. Jadval bir daqiqada tayyor bo'ladi."
    ]
    link = _link(db, owner)
    assert (link.status, link.mode, link.google_email) == (
        "preparing",
        "single",
        "egasi@gmail.com",
    )
    assert (f"{TASKS}.prepare_sheet_task", (str(link.id),)) in queued
    panel = client.get("/api/v1/destinations/sheet", headers=headers).json()["panel"]
    assert (panel["state"], panel["poll_seconds"]) == ("preparing", 3)

    assert prepare_sheet(db, link_id=str(link.id)) == "created"
    assert (f"{TASKS}.deliver_to_sheet_task", (str(link.id),)) in queued
    made = google.files["sheet-1"]
    # The owner reads the cabinet in Russian, so the file is headed in it.
    assert made["title"] == "TargetologAI — Клиенты"
    assert made["headers"][:3] == ["ID", "Имя", "Телефон"]

    first = _lead(db, owner, form, "Ali", is_test=True)
    second = _lead(db, owner, form, "Vali")
    assert deliver_to_sheet(db, link_id=str(link.id)) == "sent:2"

    rows = google.rows("sheet-1")
    assert [row[:2] for row in rows] == [
        [str(first.id), "Ali"],
        [str(second.id), "Vali"],
    ]
    assert rows[0][8:10] == ["Ariza", "Пробный"]
    statuses = db.scalars(select(LeadDelivery.status)).all()
    assert sorted(statuses) == ["delivered", "delivered"]
    link = _link(db, owner)
    assert link.caught_up_at is not None
    panel = client.get("/api/v1/destinations/sheet", headers=headers).json()["panel"]
    assert (panel["state"], panel["written"], panel["url"]) == (
        "active",
        2,
        "https://docs.google.com/sheet-1",
    )
    # Caught up: the minute sweep leaves the link alone until a lead comes.
    queued.clear()
    assert sweep_sheets(db, now=utcnow()) == 0
    _lead(db, owner, form, "Yangi")
    assert sweep_sheets(db, now=utcnow()) == 1
    assert queued == [(f"{TASKS}.deliver_to_sheet_task", (str(link.id),))]


def test_presses_are_refused_with_django_s_sentences(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    owner, _ = _owner(db, paid=False)
    headers = _auth(owner)

    unpaid = client.post(
        "/api/v1/destinations/google/start", json={"mode": "single"}, headers=headers
    )
    no_form = client.post(
        "/api/v1/destinations/google/start",
        json={"mode": "own_file", "scope": "one"},
        headers=headers,
    )
    stale = client.get(
        "/api/v1/destinations/google/callback",
        params={"state": "nope", "code": "c"},
        follow_redirects=False,
    )
    nothing = client.post("/api/v1/destinations/sheet/recreate", headers=headers)
    gone = client.post("/api/v1/destinations/sheet/disconnect", headers=headers)
    expired = client.get("/api/v1/destinations/sheet/picker", headers=headers)

    assert unpaid.json() == {
        "detail": "Google jadvalni ulash uchun faol obuna kerak.",
        "code": "sheet_subscription_required",
    }
    assert no_form.status_code == 422
    assert no_form.json()["problems"] == {"only_form": "Qaysi forma ekanini tanlang."}
    assert parse_qs(urlparse(stale.headers["location"]).query)["error"] == [
        "Ulanish eskirgan. Tugmani qaytadan bosing."
    ]
    assert nothing.json()["code"] == "no_sheet_link"
    assert gone.json()["detail"] == "Google jadval ulanmagan."
    assert (expired.status_code, expired.json()["code"]) == (410, "picker_expired")


def test_a_refusal_on_google_s_screen_and_a_missing_tick(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    owner, _ = _owner(db)
    headers = _auth(owner)
    started = client.post(
        "/api/v1/destinations/google/start", json={"mode": "single"}, headers=headers
    )
    state = parse_qs(urlparse(started.json()["url"]).query)["state"][0]

    declined = client.get(
        "/api/v1/destinations/google/callback",
        params={"state": state, "error": "access_denied"},
        follow_redirects=False,
    )
    google.scope = "openid email"
    unticked = _connect(client, headers, {"mode": "single"})

    assert parse_qs(urlparse(declined.headers["location"]).query)["error"] == [
        "Google ruxsat bermadi. Jadvalga yozish uchun ruxsat kerak."
    ]
    assert parse_qs(urlparse(unticked.headers["location"]).query)["error"] == [
        "Google oynasida jadvalga yozish belgisini qoldiring va qaytadan urinib "
        "ko'ring."
    ]
    assert db.scalar(select(SheetLink)) is None


def test_the_owner_s_own_file_is_picked_and_given_a_tab(
    client: TestClient,
    db: Session,
    google: FakeGoogle,
    queued: list[tuple[str, tuple[object, ...]]],
) -> None:
    owner, form = _owner(db)
    headers = _auth(owner)

    back = _connect(
        client,
        headers,
        {"mode": "own_file", "scope": "one", "only_form": str(form.id)},
    )

    assert parse_qs(urlparse(back.headers["location"]).query)["sheet"] == ["choosing"]
    link = _link(db, owner)
    assert (link.status, link.only_form_id) == ("choosing", form.id)
    assert not [name for name, _ in queued if name.endswith("prepare_sheet_task")]
    picker = client.get("/api/v1/destinations/sheet/picker", headers=headers)
    assert picker.headers["cache-control"] == "no-store"
    assert picker.json() == {
        "token": "picker-at",
        "key": "key",
        "app_id": "123",
        "locale": "ru",
    }

    bad = client.post(
        "/api/v1/destinations/sheet/pick", json={"file_id": "x"}, headers=headers
    )
    assert bad.json()["code"] == "bad_file_choice"
    google.files["own-file-123"] = {
        "tabs": [{"properties": {"sheetId": 0, "title": "TargetologAI — Ariza"}}]
    }
    picked = client.post(
        "/api/v1/destinations/sheet/pick",
        json={"file_id": "own-file-123"},
        headers=headers,
    )
    assert picked.json()["state"] == "preparing"

    assert prepare_sheet(db, link_id=str(link.id)) == "tab_added"
    link = _link(db, owner)
    tab = google.files["own-file-123"]["updates"][0]["addSheet"]["properties"]
    assert tab["title"] == "TargetologAI — Ariza (2)"
    assert (link.status, link.sheet_id) == ("active", str(tab["sheetId"]))
    logs = db.scalars(select(ActionLog).order_by(ActionLog.created_at)).all()
    assert [(log.action, log.status) for log in logs] == [
        ("sheet_connect", "applied"),
        ("sheet_pick", "applied"),
    ]


def test_a_permission_taken_back_breaks_the_link_and_disconnecting_hands_it_back(
    client: TestClient,
    db: Session,
    google: FakeGoogle,
    queued: list[tuple[str, tuple[object, ...]]],
) -> None:
    owner, form = _owner(db)
    headers = _auth(owner)
    link = _active(db, owner)
    google.files["sheet-1"] = {"tabs": [{"properties": {"sheetId": 0}}]}
    _lead(db, owner, form, "Ali")
    google.refresh_error = "invalid_grant"

    assert deliver_to_sheet(db, link_id=str(link.id)) == "broken:revoked"
    panel = client.get("/api/v1/destinations/sheet", headers=headers).json()["panel"]
    assert (panel["state"], panel["reason"], panel["needs_new_sheet"]) == (
        "broken",
        "revoked",
        False,
    )
    refused = client.post("/api/v1/destinations/sheet/recreate", headers=headers)
    assert refused.json()["detail"] == "Jadval joyida - yangisini yaratish shart emas."

    off = client.post("/api/v1/destinations/sheet/disconnect", headers=headers)
    assert off.json()["state"] == "off"
    assert (f"{TASKS}.revoke_sheet_token_task", (str(link.id),)) in queued
    assert revoke_sheet_token(db, link_id=str(link.id)) == "revoked"
    link = _link(db, owner)
    assert (link.token_fingerprint, bytes(link.token_encrypted)) == ("", b"")
    log = db.scalar(select(ActionLog))
    assert log is not None
    assert (log.action, log.status) == ("sheet_disconnect", "applied")
    assert sweep_sheet_checks(db) == 0


def test_a_file_in_the_bin_stops_the_link_and_a_new_one_is_made(
    client: TestClient,
    db: Session,
    google: FakeGoogle,
    queued: list[tuple[str, tuple[object, ...]]],
) -> None:
    owner, _ = _owner(db)
    headers = _auth(owner)
    link = _active(db, owner)
    google.files["sheet-1"] = {"trashed": True, "tabs": []}

    assert sweep_sheet_checks(db) == 1
    assert check_sheet_link(db, link_id=str(link.id)) == "trashed"
    panel = client.get("/api/v1/destinations/sheet", headers=headers).json()["panel"]
    assert (panel["reason"], panel["reason_label"], panel["needs_new_sheet"]) == (
        "trashed",
        "Jadval savatchada",
        True,
    )

    again = client.post("/api/v1/destinations/sheet/recreate", headers=headers)

    assert again.json()["state"] == "preparing"
    link = _link(db, owner)
    assert (link.spreadsheet_id, link.broken_reason) == ("", "")
    assert prepare_sheet(db, link_id=str(link.id)) == "created"
    assert _link(db, owner).spreadsheet_id == "sheet-1"
    assert google.made == 1


def test_another_way_of_writing_needs_no_trip_to_google(
    client: TestClient,
    db: Session,
    google: FakeGoogle,
    queued: list[tuple[str, tuple[object, ...]]],
) -> None:
    owner, form = _owner(db)
    headers = _auth(owner)
    link = _active(db, owner)
    _lead(db, owner, form, "Ali")

    same = client.post(
        "/api/v1/destinations/sheet/mode", json={"mode": "single"}, headers=headers
    )
    own = client.post(
        "/api/v1/destinations/sheet/mode",
        json={"mode": "own_file", "scope": "all"},
        headers=headers,
    )
    changed = client.post(
        "/api/v1/destinations/sheet/mode", json={"mode": "per_form"}, headers=headers
    )

    assert same.json()["code"] == "sheet_mode_unchanged"
    assert own.json()["url"].startswith("https://accounts.google.com/")
    assert changed.json()["detail"] == (
        "Yozish usuli o'zgardi. Yangi mijozlar endi shu usulda yoziladi."
    )
    link = _link(db, owner)
    assert (link.status, link.mode, link.spreadsheet_id) == (
        "preparing",
        "per_form",
        "",
    )
    assert prepare_sheet(db, link_id=str(link.id)) == "files_lost:0"

    late = _lead(db, owner, form, "Vali")
    assert deliver_to_sheet(db, link_id=str(link.id)) == "sent:1"
    sheet = db.scalar(select(FormSheet))
    assert sheet is not None and sheet.form_id == form.id
    assert google.files[sheet.spreadsheet_id]["title"] == "TargetologAI — Ariza"
    assert [row[0] for row in google.rows(sheet.spreadsheet_id)] == [str(late.id)]
    delivery = db.scalar(select(LeadDelivery))
    assert delivery is not None and delivery.form_sheet_id == sheet.id
