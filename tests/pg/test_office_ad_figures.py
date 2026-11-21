"""The dashboard's advertising figures: the superuser picks the office
account's campaigns and the plans, and spend, revenue, ROAS, CAC, conversion
and deal time are counted for the people those campaigns brought."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.dates import localtime, office_zone
from app.common.db import utcnow
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign
from app.modules.backoffice.constants import Role
from app.modules.backoffice.selectors import ad_figures as figures_module
from app.modules.billing.constants import InvoiceStatus
from app.modules.billing.models import Plan
from app.modules.metrics.models import FxRate, MetricsDaily
from tests.pg.test_boards_help_idle import _own_cabinet
from tests.pg.test_office_actions import _staff
from tests.pg.test_office_dashboard import _bill
from tests.pg.test_supportchat import _user

DASH = "/api/v1/office/acquisition"
PICK = "/api/v1/office/acquisition/campaigns"
PLANS = "/api/v1/office/acquisition/plans"
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


def _plans(db: Session) -> tuple[Plan, Plan]:
    start = Plan(code="start", name="Start", price=49000, currency="UZS", period_days=7,
                 max_adsets=1, llm_cost_limit_minor=0)  # fmt: skip
    pro = Plan(code="pro", name="Pro", price=490000, currency="UZS", period_days=30,
               max_adsets=10, llm_cost_limit_minor=0)  # fmt: skip
    db.add_all([start, pro])
    db.commit()
    return start, pro


def _joined(db: Session, email: str, day: date, **extra: object):  # type: ignore[no-untyped-def]
    return _user(db, email, date_joined=datetime.combine(day, time(12), office_zone()),
                 **extra)  # fmt: skip


def test_only_the_superuser_picks_the_plans(
    client: TestClient, db: Session, office: object
) -> None:
    _, pro = _plans(db)
    _, chief = _staff(db, email="chief@office.test", superuser=True)
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")
    assert client.get(PLANS, headers=finance).status_code == 404
    assert client.put(PLANS, headers=finance, json={"plan_ids": []}).status_code == 404

    body = client.get(PLANS, headers=chief).json()
    assert {row["code"] for row in body["plans"]} == {"start", "pro"}
    assert not any(row["picked"] for row in body["plans"])

    stranger = "00000000-0000-0000-0000-000000000001"
    refused = client.put(
        PLANS, headers=chief, json={"plan_ids": [str(pro.id), stranger]}
    )
    assert refused.status_code == 422, refused.text
    done = client.put(PLANS, headers=chief, json={"plan_ids": [str(pro.id)]})
    assert done.status_code == 200, done.text
    assert [r["code"] for r in done.json()["plans"] if r["picked"]] == ["pro"]


def test_sign_ups_from_the_picked_campaigns_and_what_they_paid(
    client: TestClient,
    db: Session,
    office: tuple[object, date],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marks from yesterday on; the days before are estimated from Meta's
    results, never above the sign-ups of those days."""
    _, today = office
    monkeypatch.setattr(figures_module, "EXACT_FROM", today - timedelta(days=1))
    start, pro = _plans(db)
    _, chief = _staff(db, email="chief@office.test", superuser=True)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    client.put(PICK, headers=chief, json={"campaign_ids": ["c_site"]})
    client.put(PLANS, headers=chief, json={"plan_ids": [str(pro.id)]})
    site = db.scalar(select(Campaign).where(Campaign.external_id == "c_site"))
    site.name = "Sayt lid 18"
    owner = site.owner_id
    db.add(MetricsDaily(owner_id=owner, provider=PROVIDER, ad_account_id=site.ad_account_id,
                        level="campaign", external_id="c_site", campaign_external_id="c_site",
                        date=today - timedelta(days=3), spend_minor=0, leads_reported=2,
                        currency="USD", synced_at=utcnow()))  # fmt: skip
    db.commit()

    # Estimated days: 4 signed up, Meta saw 2 from the picked campaign.
    early = today - timedelta(days=3)
    first = _joined(db, "e1@client.test", early)
    second = _joined(db, "e2@client.test", early)
    _joined(db, "e3@client.test", early)
    _joined(db, "e4@client.test", early)
    _bill(db, pro, first.id, amount_minor=10_000_000, status=InvoiceStatus.PAID,
          paid_at=first.date_joined + timedelta(days=1))  # fmt: skip
    _bill(db, start, second.id, amount_minor=4_900_000, status=InvoiceStatus.PAID,
          paid_at=second.date_joined)  # Start is not picked: no sale here  # fmt: skip

    # Marked days: the ad set, the campaign's name as Meta wrote it, another campaign.
    late = today - timedelta(days=1)
    by_adset = _joined(db, "m1@client.test", late, signup_utm={"term": "s_c_site"})
    _joined(db, "m2@client.test", late, signup_utm={"campaign": "Sayt+lid+18"})
    _joined(db, "m3@client.test", late, signup_utm={"term": "s_c_webinar"})
    _joined(db, "m4@client.test", late, signup_utm={"source": "chatgpt.com"})
    _bill(db, pro, by_adset.id, amount_minor=20_000_000, status=InvoiceStatus.PAID,
          paid_at=by_adset.date_joined + timedelta(hours=3))  # fmt: skip
    _bill(db, pro, by_adset.id, amount_minor=20_000_000, status=InvoiceStatus.PAID,
          paid_at=by_adset.date_joined + timedelta(days=30))  # a renewal by now  # fmt: skip
    db.commit()

    params = {"period": "range", "since": (today - timedelta(days=4)).isoformat(),
              "until": today.isoformat()}  # fmt: skip
    seen = client.get(DASH, headers=chief, params=params)
    assert seen.status_code == 200, seen.text
    fig = seen.json()
    assert fig["spend"] == [{"currency": "USD", "amount_minor": 10_000}]
    spend_uzs = 100 * 12000 * 100
    assert fig["spend_uzs_minor"] == spend_uzs
    # 2 of 4 estimated (half of their 1 payer and 100 000) + 2 marked, 1 paid.
    assert fig["signups"] == 4.0 and fig["payers"] == 1.5
    revenue = 5_000_000 + 40_000_000
    assert fig["revenue_uzs_minor"] == revenue
    assert fig["roas"] == round(revenue / spend_uzs, 2)
    assert fig["cac_uzs_minor"] == round(spend_uzs / 1.5)
    assert fig["conversion_pct"] == 37.5
    assert fig["deal_seconds"] == 3 * 3600, "the marked deal weighs a whole one"
    assert fig["estimated_from"] == params["since"]
    assert fig["estimated_until"] == (today - timedelta(days=2)).isoformat()
    assert fig["plans_picked"] == 1

    marked_only = client.get(DASH, headers=chief, params={"period": "today"}).json()
    assert marked_only["estimated_from"] is None and marked_only["signups"] == 0

    assert client.get(DASH, headers=support).status_code == 404, "money roles only"


def test_estimated_sign_ups_never_exceed_those_who_signed_up(
    client: TestClient,
    db: Session,
    office: tuple[object, date],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, today = office
    monkeypatch.setattr(figures_module, "EXACT_FROM", today + timedelta(days=1))
    _, chief = _staff(db, email="chief@office.test", superuser=True)
    client.put(PICK, headers=chief, json={"campaign_ids": ["c_site"]})
    # Meta: 3 today + 3 yesterday; signed up: the fixture's one customer.
    fig = client.get(DASH, headers=chief, params={"period": "7"}).json()
    assert fig["signups"] == 1.0
    assert fig["plans_picked"] == 0 and fig["payers"] == 0 and fig["roas"] is None


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
