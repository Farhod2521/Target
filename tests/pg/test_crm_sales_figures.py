"""A pair's leads set against the advertising that brought them: whose spend
counts, in which currency, and what the answers are."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.crm import selectors
from app.modules.crm.selectors.stats import Stats, stats
from app.modules.integrations.models import AdAccount
from app.modules.metrics.models import FxRate, MetricsDaily
from core.metrics.sales import answers
from tests.pg.test_crm_http import CRM, _auth, _owner, _running


def _lead_day(db: Session) -> date:
    """The ad account's day the three leads of ``_owner`` arrived on."""
    account = db.scalar(select(AdAccount))
    assert account is not None
    return localtime(utcnow() - timedelta(hours=2), account.tzinfo()).date()


def _spend(
    db: Session,
    owner: User,
    ad: str,
    campaign: str,
    dollars: int,
    *,
    level: str = "ad",
    day: date | None = None,
) -> None:
    account = db.scalar(select(AdAccount))
    assert account is not None
    db.add(
        MetricsDaily(
            owner_id=owner.id,
            provider="meta",
            external_id=ad,
            ad_account_id=account.id,
            level=level,
            campaign_external_id=campaign,
            date=day or _lead_day(db),
            spend_minor=dollars * 100,
            currency="USD",
            synced_at=utcnow(),
        )
    )
    db.commit()


def _rate(db: Session, rate: str = "12000") -> None:
    db.add(
        FxRate(
            day=_lead_day(db) - timedelta(days=5),
            currency="USD",
            rate=Decimal(rate),
        )
    )
    db.commit()


def _read(db: Session, owner: User) -> Stats:
    db.expire_all()
    viewer = selectors.viewer_for(db, user=db.get(User, owner.id), wanted="")
    return stats(db, viewer=viewer, period="7", now=utcnow())


def _som(client: TestClient, head: dict[str, str]) -> None:
    saved = client.post(
        f"{CRM}/settings/currency", headers=head, json={"currency": "UZS"}
    )
    assert saved.is_success, saved.text


def _sell(client: TestClient, head: dict[str, str], board: dict[str, Any]) -> None:
    card = board["columns"][0]["cards"][0]["id"]
    sold = client.post(
        f"{CRM}/cards/{card}/win", headers=head, json={"amount": "600000"}
    )
    assert sold.is_success, sold.text


def test_spend_in_dollars_and_sales_in_som_meet_in_the_crms_currency(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    _som(client, head)
    _sell(client, head, board)
    _rate(db)
    _spend(db, owner, "ad_1", "c_1", 10)
    # Spent and brought nobody, in a campaign that feeds the CRM: counted.
    _spend(db, owner, "ad_2", "c_1", 5)
    # A campaign no lead of which ever reached the CRM: not counted.
    _spend(db, owner, "ad_9", "c_9", 7)
    # The same money again at the ad set's level: not counted twice.
    _spend(db, owner, "as_1", "c_1", 15, level="adset")

    found = _read(db, owner)
    total = found.totals
    told = answers(total)

    # $15 at 12 000 = 180 000 so'm; one sale of 600 000 so'm from 3 leads.
    assert found.currency == "UZS"
    assert (total.spend_minor, total.spend_unpriced_days) == (18_000_000, 0)
    assert (total.leads, total.won, total.revenue_minor) == (3, 1, 60_000_000)
    assert told["roas"].value == Decimal("3.33")
    assert told["cac"].value == 18_000_000
    assert told["cpl"].value == 6_000_000
    assert told["conversion"].value == Decimal("33.33")
    assert told["deal_time"].value is not None
    by_ad = {key: tally for key, tally in found.ads}
    assert (by_ad["ad_1"].spend_minor, by_ad["ad_1"].leads) == (12_000_000, 3)
    assert (by_ad["ad_2"].spend_minor, by_ad["ad_2"].leads) == (6_000_000, 0)
    assert "ad_9" not in by_ad
    assert [(key, tally.spend_minor) for key, tally in found.campaigns] == [
        ("c_1", 18_000_000)
    ]
    on_day = found.daily[found.days.index(_lead_day(db))]
    assert (on_day.spend_minor, on_day.leads, on_day.won) == (18_000_000, 3, 1)
    assert sum(day.spend_minor or 0 for day in found.daily) == 18_000_000
    # The seller has sales and no spend of his own.
    ((_, seller, _),) = found.managers
    assert seller.spend_minor is None
    assert answers(seller)["cac"].missing == "not_here"
    assert answers(seller)["revenue"].value == 60_000_000
    assert found.completeness.level == "low"


def test_only_the_ticked_adverts_spend_counts_and_one_that_brought_a_card(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _som(client, head)
    _rate(db)
    _spend(db, owner, "ad_1", "c_1", 10)
    _spend(db, owner, "ad_2", "c_1", 5)
    _spend(db, owner, "ad_3", "c_1", 2)
    flow = {
        "since": "month",
        "every_ad": False,
        "ad": ["ad_2"],
        "offered": ["ad_1", "ad_2"],
        "take_new_ads": False,
    }
    assert client.post(f"{CRM}/settings/flow", headers=head, json=flow).is_success

    ticked = _read(db, owner).totals.spend_minor
    # ad_2 is ticked; ad_1 is not, but its leads are cards here: $15.
    assert ticked == 18_000_000

    flow["take_new_ads"] = True
    assert client.post(f"{CRM}/settings/flow", headers=head, json=flow).is_success

    # ad_3 was not there to tick, and new adverts are taken too: $17.
    assert _read(db, owner).totals.spend_minor == 20_400_000


def test_spend_no_rate_prices_is_left_out_and_counted(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    _som(client, head)
    _sell(client, head, board)
    _spend(db, owner, "ad_1", "c_1", 10)

    total = _read(db, owner).totals
    told = answers(total)

    assert (total.spend_minor, total.spend_unpriced_days) == (0, 1)
    assert told["roas"].missing == "no_spend"
    assert told["revenue"].value == 60_000_000


def test_the_same_currency_on_both_sides_needs_no_rate(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    assert client.post(
        f"{CRM}/cards/{card}/win", headers=head, json={"amount": "90"}
    ).is_success
    _spend(db, owner, "ad_1", "c_1", 30)

    found = _read(db, owner)
    told = answers(found.totals)

    assert found.currency == "USD"
    assert (found.totals.spend_minor, found.totals.revenue_minor) == (3000, 9000)
    assert told["roas"].value == Decimal("3.00")
    assert told["cac"].value == 3000


def test_the_range_before_is_counted_the_same_way(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _spend(db, owner, "ad_1", "c_1", 30)
    _spend(db, owner, "ad_1", "c_1", 8, day=_lead_day(db) - timedelta(days=9))

    found = _read(db, owner)

    assert found.totals.spend_minor == 3000
    assert found.earlier is not None
    assert (found.earlier.spend_minor, found.earlier.leads) == (800, 0)


def test_the_crm_page_carries_the_sales_cells_cut_every_way(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    _som(client, head)
    _sell(client, head, board)
    _rate(db)
    _spend(db, owner, "ad_1", "c_1", 10)
    _spend(db, owner, "ad_2", "c_1", 5)

    answer = client.get(f"{CRM}/stats?period=7", headers=head)

    assert answer.status_code == 200, answer.text
    sales = answer.json()["sales"]
    assert (sales["state"], sales["currency"]) == ("on", "UZS")
    assert answer.json()["range"]["time_zone"] == "Asia/Tashkent"
    assert [m["key"] for m in sales["metrics"]][:4] == [
        "spend",
        "revenue",
        "roas",
        "cac",
    ]
    assert sales["totals"]["spend"] == {"value": 18_000_000, "missing": None}
    assert sales["totals"]["revenue"] == {"value": 60_000_000, "missing": None}
    assert sales["totals"]["roas"] == {"value": 3.33, "missing": None}
    assert sales["totals"]["cac"] == {"value": 18_000_000, "missing": None}
    assert sales["totals"]["conversion"]["value"] == 33.33
    assert sales["totals"]["deal_time"]["value"] is not None
    assert sales["earlier"]["leads"] == {"value": 0, "missing": None}
    assert sales["earlier"]["roas"]["missing"] == "no_base"
    assert sales["completeness"]["level"] == "low"
    assert sales["left_out"] == {"sales": 0, "spend_days": 0}
    assert sales["missing_words"]["no_sales"]
    assert [
        (row["id"], row["cells"]["spend"]["value"]) for row in sales["campaigns"]
    ] == [("c_1", 18_000_000)]
    by_ad = {row["id"]: row["cells"] for row in sales["ads"]}
    assert by_ad["ad_1"]["roas"]["value"] == 5.0
    # Spent, brought nobody: no sale to speak of, and a price per lead of nothing.
    assert by_ad["ad_2"]["roas"]["missing"] == "no_base"
    assert by_ad["ad_2"]["cpl"]["missing"] == "no_base"
    (seller,) = sales["managers"]
    assert seller["cells"]["cac"]["missing"] == "not_here"
    assert seller["cells"]["revenue"]["value"] == 60_000_000
    assert len(sales["daily"]) == 7
    assert sum(day["cells"]["spend"]["value"] for day in sales["daily"]) == 18_000_000
    # The old fields are still there for the page as it is built today.
    assert answer.json()["totals"]["revenue_minor"] == 60_000_000


def test_the_process_tells_each_column_now_and_how_long_cards_stay(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    _sell(client, head, board)

    process = client.get(f"{CRM}/stats?period=7", headers=head).json()["process"]

    by_kind = {row["stage"]["kind"]: row for row in process}
    assert [row["stage"]["kind"] for row in process] == [
        c["stage"]["kind"] for c in board["columns"]
    ]
    # Two cards still wait in the first column; one left it for «Sotildi».
    assert (by_kind["new"]["now"], by_kind["new"]["stays"]) == (2, 1)
    assert by_kind["new"]["waiting_min"] is not None
    assert by_kind["new"]["stay_min"] is not None
    assert (by_kind["won"]["now"], by_kind["won"]["stays"]) == (1, 0)
    assert by_kind["won"]["stay_min"] is None
    # A sold card is not waiting for anybody.
    assert by_kind["won"]["waiting_min"] is None
    assert not any(row["approximate"] for row in process)


def test_the_dashboard_and_the_expert_board_carry_the_same_sales_block(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    _som(client, head)
    _sell(client, head, board)
    _rate(db)
    _spend(db, owner, "ad_1", "c_1", 10)

    crm = client.get(f"{CRM}/stats?period=7", headers=head).json()["sales"]
    plain = client.get("/api/v1/metrics/numbers?period=7", headers=head)
    expert = client.get("/api/v1/metrics/expert?period=7", headers=head)

    assert plain.status_code == 200, plain.text
    assert expert.status_code == 200, expert.text
    for block in (plain.json()["sales"], expert.json()["sales"]):
        assert block["totals"] == crm["totals"]
        assert block["completeness"] == crm["completeness"]
        assert block["currency"] == "UZS"
        assert "campaigns" not in block


def test_with_the_crm_not_set_up_the_dashboard_says_so_in_every_cell(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))

    sales = client.get("/api/v1/metrics/numbers?period=7", headers=head).json()["sales"]

    assert sales["state"] == "draft"
    assert {cell["missing"] for cell in sales["totals"].values()} == {"no_crm"}
    assert sales["completeness"]["level"] == "off"
