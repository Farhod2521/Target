"""The dashboard's advertising figures: the superuser picks the office
account's campaigns, and spend, revenue, ROAS, CAC, conversion and deal time
are counted for the window."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import InvoiceStatus
from app.modules.billing.models import Plan
from app.modules.metrics.models import FxRate, MetricsDaily
from tests.pg.test_boards_help_idle import _own_cabinet
from tests.pg.test_office_actions import _shop, _staff
from tests.pg.test_office_dashboard import _bill
from tests.pg.test_supportchat import _user

DASH = "/api/v1/office/acquisition"
PICK = "/api/v1/office/acquisition/campaigns"
RATE = Decimal("12000")


@pytest.fixture
def office(db: Session, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """The office account with three campaigns - one to targetolog.ai, one to
    the webinar, one Meta deleted - and a customer's account beside it."""
    owner = _user(db, "office@targetolog.test", is_staff=True)
    account, _ = _own_cabinet(db, owner)
    monkeypatch.setattr(settings, "office_ad_account", account.external_id)
    other_owner = _user(db, "other@client.test")
    other, _ = _own_cabinet(db, other_owner)
    today = localtime(utcnow()).date()
    for external_id, link in (("c_site", "https://targetolog.ai/?utm=1"),
                              ("c_webinar", "https://vebinar.targetolog.ai/")):  # fmt: skip
        campaign = Campaign(owner_id=owner.id, provider=PROVIDER, external_id=external_id,
                            name=external_id, ad_account_id=account.id,
                            effective_status="ACTIVE")  # fmt: skip
        db.add(campaign)
        db.flush()
        adset = AdSet(owner_id=owner.id, provider=PROVIDER, external_id=f"s_{external_id}",
                      campaign_id=campaign.id)  # fmt: skip
        db.add(adset)
        db.flush()
        db.add(AdCreative(owner_id=owner.id, provider=PROVIDER,
                          external_id=f"cr_{external_id}", link_url=link,
                          ad_account_id=account.id))  # fmt: skip
        db.add(Ad(owner_id=owner.id, provider=PROVIDER, external_id=f"a_{external_id}",
                  adset_id=adset.id, creative_external_id=f"cr_{external_id}"))  # fmt: skip
    db.add(Campaign(owner_id=other_owner.id, provider=PROVIDER, external_id="c_foreign",
                    name="Mijoz", ad_account_id=other.id))  # fmt: skip

    def spent(acc, who, external_id, day, minor, name=""):  # type: ignore[no-untyped-def]
        db.add(MetricsDaily(owner_id=who.id, provider=PROVIDER, ad_account_id=acc.id,
                            level="campaign", external_id=external_id,
                            campaign_external_id=external_id, object_name=name,
                            date=day, spend_minor=minor, leads_reported=3,
                            currency="USD", synced_at=utcnow()))  # fmt: skip

    spent(account, owner, "c_site", today, 5_000)  # $50
    spent(account, owner, "c_site", today - timedelta(days=1), 5_000)
    spent(account, owner, "c_site", today - timedelta(days=60), 9_999)  # outside 7 days
    spent(account, owner, "c_webinar", today, 7_000)
    spent(account, owner, "c_gone", today, 1_000, name="O'chirilgan")
    spent(other, other_owner, "c_foreign", today, 100_000)
    db.add(FxRate(day=today - timedelta(days=5), currency="USD", rate=RATE))
    db.commit()
    return account, today


def test_only_the_superuser_picks_and_only_the_office_campaigns(
    client: TestClient, db: Session, office: object
) -> None:
    _, chief = _staff(db, email="chief@office.test", superuser=True)
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")

    assert client.get(PICK, headers=finance).status_code == 404
    assert (
        client.put(PICK, headers=finance, json={"campaign_ids": []}).status_code == 404
    )

    body = client.get(PICK, headers=chief).json()
    rows = {row["id"]: row for row in body["campaigns"]}
    assert set(rows) == {"c_site", "c_webinar", "c_gone"}, "a customer's is not listed"
    assert rows["c_site"]["sites"] == ["targetolog.ai"]
    assert rows["c_webinar"]["sites"] == ["vebinar.targetolog.ai"]
    assert (
        rows["c_gone"]["status"] == "DELETED"
        and rows["c_gone"]["name"] == "O'chirilgan"
    )
    assert rows["c_site"]["spend_minor"] == 19_999 and not rows["c_site"]["picked"]

    refused = client.put(
        PICK, headers=chief, json={"campaign_ids": ["c_site", "c_foreign"]}
    )
    assert refused.status_code == 422, refused.text
    assert not any(
        row["picked"] for row in client.get(PICK, headers=chief).json()["campaigns"]
    )

    done = client.put(PICK, headers=chief, json={"campaign_ids": ["c_site", "c_gone"]})
    assert done.status_code == 200, done.text
    assert {r["id"] for r in done.json()["campaigns"] if r["picked"]} == {
        "c_site",
        "c_gone",
    }
    again = client.put(PICK, headers=chief, json={"campaign_ids": ["c_webinar"]})
    assert {r["id"] for r in again.json()["campaigns"] if r["picked"]} == {"c_webinar"}


def test_the_six_figures_for_the_picked_campaigns(
    client: TestClient, db: Session, office: tuple[object, date]
) -> None:
    _, chief = _staff(db, email="chief@office.test", superuser=True)
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    empty = client.get(DASH, headers=finance, params={"period": "7"}).json()
    assert empty["picked"] == 0 and empty["spend_uzs_minor"] == 0
    assert empty["roas"] is None and empty["can_pick"] is False

    client.put(PICK, headers=chief, json={"campaign_ids": ["c_site", "c_gone"]})

    shop, pro = _shop(db)  # joined 3 days ago
    start = Plan(code="start", name="Start", price=49000, currency="UZS", period_days=7,
                 max_adsets=1, llm_cost_limit_minor=0)  # fmt: skip
    db.add(start)
    db.flush()
    now = utcnow()
    shop.date_joined = now - timedelta(days=3)
    _bill(db, start, shop.id, amount_minor=4_900_000, status=InvoiceStatus.PAID,
          paid_at=now - timedelta(days=3))  # fmt: skip
    _bill(db, pro, shop.id, amount_minor=49_000_000, status=InvoiceStatus.PAID,
          paid_at=now - timedelta(days=1))  # fmt: skip
    _user(db, "joined@client.test")  # joined, never paid
    old = _user(db, "old@client.test", date_joined=now - timedelta(days=90))
    _bill(db, pro, old.id, amount_minor=12_000_000, status=InvoiceStatus.PAID,
          paid_at=now - timedelta(days=60))  # fmt: skip
    # A renewal: revenue, not a new payer.
    _bill(db, pro, old.id, amount_minor=12_000_000, status=InvoiceStatus.PAID,
          paid_at=now - timedelta(hours=2))  # fmt: skip
    db.commit()

    seen = client.get(DASH, headers=chief, params={"period": "7"})
    assert seen.status_code == 200, seen.text
    fig = seen.json()
    assert fig["can_pick"] is True and fig["picked"] == 2
    assert fig["spend"] == [{"currency": "USD", "amount_minor": 11_000}], (
        "picked only, the window only, the deleted one counted"
    )
    spend_uzs = 110 * 12000 * 100
    assert fig["spend_uzs_minor"] == spend_uzs and fig["unpriced_days"] == 0
    revenue = 4_900_000 + 49_000_000 + 12_000_000
    assert fig["revenue_uzs_minor"] == revenue
    assert fig["roas"] == round(revenue / spend_uzs, 2)
    assert fig["new_payers"] == 1 and fig["cac_uzs_minor"] == spend_uzs
    assert (fig["joined"], fig["joined_paid"], fig["conversion_pct"]) == (3, 1, 33.3), (
        "the shop, the one who never paid, the other account's owner"
    )
    assert fig["deals"] == 1, "Start is not a deal"
    assert abs(fig["deal_seconds"] - 2 * 86400) < 60

    assert client.get(DASH, headers=support).status_code == 404, "money roles only"


def test_a_day_without_a_rate_leaves_the_som_figures_unknown(
    client: TestClient, db: Session, office: tuple[object, date]
) -> None:
    _, chief = _staff(db, email="chief@office.test", superuser=True)
    client.put(PICK, headers=chief, json={"campaign_ids": ["c_site"]})
    for row in db.scalars(select(FxRate)):
        db.delete(row)
    db.commit()
    fig = client.get(DASH, headers=chief, params={"period": "7"}).json()
    assert fig["spend"] == [{"currency": "USD", "amount_minor": 10_000}]
    assert fig["spend_uzs_minor"] is None and fig["unpriced_days"] == 2
    assert fig["roas"] is None and fig["cac_uzs_minor"] is None
