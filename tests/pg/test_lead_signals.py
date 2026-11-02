"""What a night tells Meta about the day's cards, against PostgreSQL."""

from collections.abc import Sequence
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from adskit import ConversionReceiptDTO, LeadEventDTO
from adskit.errors import InvalidRequest, TemporaryFailure
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import encrypt
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.crm.models import CrmActivity, CrmCard
from app.modules.integrations.models import (
    AdAccount,
    PixelAccount,
    ProviderConnection,
)
from app.modules.leads.models import Lead, LeadSignal
from app.modules.leads.services import signals
from tests.pg.test_crm_http import CRM, _auth, _owner, _running


class Port:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[LeadEventDTO], bool]] = []
        self.refuse: str = ""
        self.fail = False

    def report_window_days(self) -> int:
        return 7

    def report_leads(
        self,
        *,
        dataset: Any,
        events: Sequence[LeadEventDTO],
        token: str,
        dry_run: bool = True,
    ) -> ConversionReceiptDTO:
        if self.fail:
            raise TemporaryFailure("later")
        if self.refuse and any(e.lead.id == self.refuse for e in events):
            raise InvalidRequest("bad lead_id")
        self.calls.append((dataset.id, list(events), dry_run))
        return ConversionReceiptDTO(
            dataset=dataset, accepted=len(events), trace_id="trace"
        )

    @property
    def sent(self) -> list[tuple[str, str]]:
        return [
            (event.lead.id, event.stage)
            for _, events, _ in self.calls
            for event in events
        ]


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())


@pytest.fixture
def port(monkeypatch: pytest.MonkeyPatch) -> Port:
    fake = Port()
    monkeypatch.setattr(
        signals,
        "registry",
        SimpleNamespace(get=lambda _: SimpleNamespace(conversions=fake)),
    )
    monkeypatch.setattr(signals.settings, "ads_dry_run", False)
    return fake


def _pixel(db: Session, owner: User, account: AdAccount, name: str = "px_1") -> None:
    db.add(
        PixelAccount(
            owner_id=owner.id,
            ad_account_id=account.id,
            connection_id=account.connection_id,
            provider=PROVIDER,
            external_id=name,
            name=name,
            is_active=True,
        )
    )
    db.flush()


def _ready(db: Session, *, pixel: bool = True) -> tuple[User, AdAccount]:
    owner = _owner(db)
    account = db.query(AdAccount).filter_by(owner_id=owner.id).one()
    connection = db.get(ProviderConnection, account.connection_id)
    assert connection is not None
    connection.token_encrypted = encrypt("token")
    if pixel:
        _pixel(db, owner, account)
    db.commit()
    return owner, account


def _tomorrow() -> Any:
    return utcnow() + timedelta(days=1)


def _night(db: Session, owner: User, now: Any = None) -> str:
    return signals.report_signals(db, owner_id=owner.id, now=now or _tomorrow())


def _stages(board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["stage"]["kind"]: c["stage"] for c in board["columns"]}


def _cards(board: dict[str, Any]) -> list[str]:
    return [card["id"] for card in board["columns"][0]["cards"]]


def _leadgen(db: Session, card_id: str) -> str:
    return db.get(CrmCard, card_id).lead.leadgen_id  # type: ignore[union-attr]


def test_the_night_tells_each_card_where_it_stands(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    head = _auth(owner)
    board = _running(client, head)
    stages = _stages(board)
    client.post(
        f"{CRM}/settings/quality",
        headers=head,
        json={"quality": [stages["open"]["id"]]},
    )
    good, bad, sold = _cards(board)
    client.post(
        f"{CRM}/cards/{good}/move", headers=head, json={"to": stages["open"]["id"]}
    )
    client.post(
        f"{CRM}/cards/{bad}/move", headers=head, json={"to": stages["junk"]["id"]}
    )
    client.post(f"{CRM}/cards/{sold}/win", headers=head, json={"amount": "150"})

    answer = _night(db, owner)

    assert answer == "sent:7"
    assert sorted(port.sent) == sorted(
        [
            (_leadgen(db, good), "received"),
            (_leadgen(db, good), "qualified"),
            (_leadgen(db, bad), "received"),
            (_leadgen(db, bad), "unqualified"),
            (_leadgen(db, sold), "received"),
            (_leadgen(db, sold), "qualified"),
            (_leadgen(db, sold), "converted"),
        ]
    )
    converted = next(
        e for _, events, _ in port.calls for e in events if e.stage == "converted"
    )
    assert (converted.value_minor, converted.currency) == (15000, "USD")
    stamps = [e.occurred_at for _, events, _ in port.calls for e in events]
    assert stamps == sorted(stamps)


def test_a_second_night_tells_nothing_new(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    _running(client, _auth(owner))
    _night(db, owner)
    first = len(port.sent)

    assert _night(db, owner) == "nothing_due"
    assert first == 3
    assert len(port.sent) == first


def test_today_waits_for_the_day_to_end(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    _running(client, _auth(owner))

    assert _night(db, owner, now=utcnow()) == "nothing_due"
    assert port.sent == []


def test_a_mistake_put_right_the_same_day_is_never_heard(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    head = _auth(owner)
    board = _running(client, head)
    stages = _stages(board)
    card = _cards(board)[0]
    url = f"{CRM}/cards/{card}/move"
    client.post(url, headers=head, json={"to": stages["junk"]["id"]})
    client.post(url, headers=head, json={"to": stages["open"]["id"]})

    _night(db, owner)

    assert (_leadgen(db, card), "unqualified") not in port.sent


def test_a_card_waiting_for_a_pixel_goes_as_it_stands_then(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, account = _ready(db, pixel=False)
    head = _auth(owner)
    board = _running(client, head)
    stages = _stages(board)
    card = _cards(board)[0]
    url = f"{CRM}/cards/{card}/move"
    client.post(url, headers=head, json={"to": stages["junk"]["id"]})

    assert _night(db, owner) == "no_dataset"
    assert port.sent == []
    assert db.query(LeadSignal).filter_by(status="pending").count() == 4

    client.post(url, headers=head, json={"to": stages["open"]["id"]})
    _pixel(db, owner, account)
    db.commit()
    _night(db, owner)

    assert (_leadgen(db, card), "unqualified") not in port.sent
    row = db.query(LeadSignal).filter_by(stage="unqualified").one()
    assert row.status == "withdrawn"


def test_an_old_signal_expires_instead_of_sinking_its_batch(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    _running(client, _auth(owner))
    _night(db, owner, now=utcnow() + timedelta(days=1, seconds=-1))
    port.calls.clear()
    stale = db.query(LeadSignal).first()
    assert stale is not None
    stale.status = "pending"
    db.commit()

    answer = _night(db, owner, now=utcnow() + timedelta(days=9))

    assert answer == "nothing_ready"
    assert port.sent == []
    db.refresh(stale)
    assert stale.status == "expired"


def test_one_bad_lead_does_not_sink_the_others(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    board = _running(client, _auth(owner))
    bad = _leadgen(db, _cards(board)[0])
    port.refuse = bad

    answer = _night(db, owner)

    assert answer == "sent:2"
    failed = db.query(LeadSignal).filter_by(status="failed").one()
    assert failed.lead.leadgen_id == bad
    assert failed.last_error == "bad lead_id"
    assert db.query(LeadSignal).filter_by(status="sent").count() == 2


def test_a_passing_failure_leaves_the_night_for_tomorrow(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    _running(client, _auth(owner))
    port.fail = True

    assert _night(db, owner) == "provider_failed"
    assert db.query(LeadSignal).filter_by(status="pending").count() == 3

    port.fail = False
    assert _night(db, owner) == "sent:3"


def test_a_rehearsal_sends_nothing_and_stamps_nothing(
    client: TestClient,
    db: Session,
    port: Port,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(signals.settings, "ads_dry_run", True)
    owner, _ = _ready(db)
    _running(client, _auth(owner))

    assert _night(db, owner) == "rehearsed:3"
    assert port.calls[0][2] is True
    assert db.query(LeadSignal).filter_by(status="pending").count() == 3


def test_each_lead_goes_to_its_own_account_s_pixel(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, account = _ready(db)
    _running(client, _auth(owner))
    other = AdAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="act_2",
        connection_id=account.connection_id,
        name="Ikkinchi",
        currency="USD",
        timezone="Asia/Tashkent",
        may_advertise=True,
        is_active=True,
    )
    db.add(other)
    db.flush()
    _pixel(db, owner, other, name="px_2")
    lead = db.query(Lead).filter_by(owner_id=owner.id).first()
    assert lead is not None
    db.add(
        LeadSignal(
            owner_id=owner.id,
            lead_id=lead.id,
            ad_account_id=other.id,
            stage="qualified",
            source="manual",
            occurred_at=utcnow() - timedelta(hours=1),
        )
    )
    db.commit()

    _night(db, owner)

    by_dataset = {dataset: events for dataset, events, _ in port.calls}
    assert {"px_1", "px_2"} == set(by_dataset)
    assert [e.stage for e in by_dataset["px_2"]] == ["qualified"]
    assert "qualified" not in [e.stage for e in by_dataset["px_1"]]


def test_a_lead_since_anonymised_is_never_named(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    _running(client, _auth(owner))
    db.execute(text("UPDATE leads SET anonymized_at = now()"))
    db.commit()

    _night(db, owner)

    assert port.sent == []
    assert db.query(LeadSignal).filter_by(status="withdrawn").count() == 3


def test_the_card_shows_what_went(client: TestClient, db: Session, port: Port) -> None:
    owner, _ = _ready(db)
    head = _auth(owner)
    board = _running(client, head)
    stages = _stages(board)
    card = _cards(board)[0]
    client.post(
        f"{CRM}/cards/{card}/move", headers=head, json={"to": stages["junk"]["id"]}
    )

    _night(db, owner)

    line = db.query(CrmActivity).filter_by(kind="sent_to_meta").one()
    assert line.text == "Sifatsiz"


def test_a_lead_marked_by_hand_is_queued_and_can_be_taken_back(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    head = _auth(owner)
    lead = db.query(Lead).filter_by(owner_id=owner.id).first()
    assert lead is not None
    url = f"/api/v1/leads/{lead.id}/verdict"

    marked = client.post(url, headers=head, json={"status": "qualified"})
    assert marked.status_code == 200
    row = db.query(LeadSignal).filter_by(lead_id=lead.id).one()
    assert (row.stage, row.status, row.source) == ("qualified", "pending", "manual")

    cleared = client.post(url, headers=head, json={"status": ""})
    assert cleared.status_code == 200
    db.refresh(row)
    assert row.status == "withdrawn"


def test_a_lead_with_a_card_answers_only_from_its_card(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    head = _auth(owner)
    _running(client, head)
    lead = db.query(CrmCard).first().lead  # type: ignore[union-attr]

    client.post(
        f"/api/v1/leads/{lead.id}/verdict", headers=head, json={"status": "qualified"}
    )

    assert db.query(LeadSignal).count() == 0


def test_the_sweep_queues_owners_at_their_hour(
    client: TestClient,
    db: Session,
    port: Port,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.leads import tasks

    owner, _ = _ready(db)
    _running(client, _auth(owner))
    queued: list[str] = []
    monkeypatch.setattr(tasks.report_signals_task, "delay", queued.append)
    two_in_tashkent = utcnow().replace(hour=21, minute=40)

    assert signals.sweep_lead_signals(db, now=two_in_tashkent) == 1
    assert queued == [str(owner.id)]
    assert signals.sweep_lead_signals(db, now=utcnow().replace(hour=9)) == 1 - 1


def test_the_migration_moves_what_django_sent_once(
    client: TestClient, db: Session
) -> None:
    from importlib import import_module

    owner, _ = _ready(db)
    board = _running(client, _auth(owner))
    card = db.get(CrmCard, _cards(board)[0])
    assert card is not None
    card.quality_sent_at = utcnow()
    db.commit()
    migration = import_module("migrations.versions.20261102_0014_lead_signals")

    db.execute(text(migration.SENT_BY_DJANGO))
    db.execute(text(migration.SENT_BY_DJANGO))
    db.commit()

    row = db.query(LeadSignal).one()
    assert (row.stage, row.status) == ("qualified", "sent")


def test_the_dashboard_reads_what_went(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db)
    head = _auth(owner)
    board = _running(client, head)
    stages = _stages(board)
    client.post(
        f"{CRM}/settings/quality",
        headers=head,
        json={"quality": [stages["open"]["id"]]},
    )
    good, bad, _third = _cards(board)
    client.post(
        f"{CRM}/cards/{good}/move", headers=head, json={"to": stages["open"]["id"]}
    )
    client.post(
        f"{CRM}/cards/{bad}/move", headers=head, json={"to": stages["junk"]["id"]}
    )
    _night(db, owner)

    numbers = client.get("/api/v1/metrics/numbers?period=7", headers=head)

    assert numbers.status_code == 200
    quality = numbers.json()["lead_quality"]
    assert quality["crm"] is True
    assert (quality["leads"], quality["marked"]) == (3, 2)
    assert (quality["qualified"], quality["unqualified"]) == (1, 1)
    assert (quality["sent"], quality["waiting"]) == (2, 0)
    assert quality["problem"] == "none"
    assert quality["last_sent_at"] is not None


def test_the_dashboard_says_when_there_is_no_pixel(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, _ = _ready(db, pixel=False)
    head = _auth(owner)
    _running(client, head)

    quality = client.get("/api/v1/metrics/numbers?period=7", headers=head).json()[
        "lead_quality"
    ]

    assert quality["problem"] == "no_pixel"
    assert quality["sent"] == 0


def test_only_what_meta_took_counts_towards_buying_on_quality(
    client: TestClient, db: Session, port: Port
) -> None:
    from app.modules.leads.selectors.reads import qualified_since

    owner, _ = _ready(db)
    head = _auth(owner)
    board = _running(client, head)
    card = _cards(board)[0]
    client.post(f"{CRM}/cards/{card}/win", headers=head, json={"amount": "150"})
    assert qualified_since(db, owner=owner, since=utcnow() - timedelta(days=1)) == 0

    _night(db, owner)

    assert qualified_since(db, owner=owner, since=utcnow() - timedelta(days=1)) == 1


def test_the_dashboard_tells_an_unchosen_pixel_from_none(
    client: TestClient, db: Session, port: Port
) -> None:
    owner, account = _ready(db, pixel=False)
    head = _auth(owner)
    _running(client, head)
    _pixel(db, owner, account)
    db.query(PixelAccount).update({"is_active": False})
    db.commit()

    quality = client.get("/api/v1/metrics/numbers?period=7", headers=head).json()[
        "lead_quality"
    ]

    assert quality["problem"] == "pixel_unselected"
