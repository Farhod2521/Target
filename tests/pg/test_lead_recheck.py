"""«Lidlarni tekshirish» and «Qabul qildim» on a page card: the work runs in
the background, so what matters is what gets queued — the page re-subscribed,
its missed leads pulled and the pages re-read for the lead terms flag."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.services import start_trial
from tests.pg.conftest import sign_up
from tests.pg.test_cabinet_flows import _cabinet

SUBSCRIBE = "app.modules.leads.tasks.subscribe_page_task"
RECONCILE = "app.modules.leads.tasks.reconcile_page_task"
SYNC_PAGES = "app.modules.integrations.tasks.sync_pages_task"


def test_recheck_of_the_current_page_pulls_missed_leads_and_rereads_terms(
    client: TestClient, db: Session, queued: list[tuple[str, tuple[object, ...]]]
) -> None:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    start_trial(db, user=user, now=utcnow())
    _, page = _cabinet(db, user)
    chosen = client.post(
        "/api/v1/connections/meta/page", json={"external_id": "page_1"}, headers=auth
    )
    assert chosen.status_code == 200, chosen.text
    queued.clear()

    done = client.post("/api/v1/connections/meta/leads/recheck", headers=auth)

    assert done.status_code == 200, done.text
    assert "«Mijozlar»" in done.json()["detail"]
    assert (SUBSCRIBE, (str(page.id),)) in queued
    assert (RECONCILE, (str(page.id),)) in queued
    assert (SYNC_PAGES, (str(page.connection_id),)) in queued


def test_recheck_of_another_page_rereads_its_terms(
    client: TestClient, db: Session, queued: list[tuple[str, tuple[object, ...]]]
) -> None:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    start_trial(db, user=user, now=utcnow())
    _, page = _cabinet(db, user)
    queued.clear()

    done = client.post(f"/api/v1/connections/meta/pages/{page.id}/leads", headers=auth)

    assert done.status_code == 200, done.text
    assert (SUBSCRIBE, (str(page.id),)) in queued
    assert (RECONCILE, (str(page.id),)) in queued
    assert (SYNC_PAGES, (str(page.connection_id),)) in queued
