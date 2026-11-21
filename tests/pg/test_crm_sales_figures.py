"""A pair's leads set against the advertising that brought them: whose spend
counts, in which currency, and what the answers are."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
from app.modules.crm import selectors
from app.modules.crm.models import CrmSetup
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
    # Not «nothing was spent»: money was spent and could not be read.
    for key in ("spend", "roas", "cac", "cpl"):
        assert told[key].missing == "no_rate"
    assert told["revenue"].value == 60_000_000
    # The advert, the campaign and the day that lost the money say so too.
    found = _read(db, owner)
    assert answers(dict(found.ads)["ad_1"])["cpl"].missing == "no_rate"
    assert answers(dict(found.campaigns)["c_1"])["spend"].missing == "no_rate"
    on_day = found.daily[found.days.index(_lead_day(db))]
    assert answers(on_day)["spend"].missing == "no_rate"


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


def test_a_rate_gone_stale_prices_nothing(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _som(client, head)
    _spend(db, owner, "ad_1", "c_1", 10)
    db.add(
        FxRate(
            day=_lead_day(db) - timedelta(days=40), currency="USD", rate=Decimal("9000")
        )
    )
    db.commit()

    total = _read(db, owner).totals

    assert (total.spend_minor, total.spend_gap) == (0, "no_rate")


def test_spend_from_before_the_crm_took_leads_is_set_against_nothing(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    day = _lead_day(db)
    _spend(db, owner, "ad_1", "c_1", 10)
    _spend(db, owner, "ad_1", "c_1", 40, day=day - timedelta(days=3))
    # The CRM began taking leads the day the three came.
    db.execute(
        update(CrmSetup).values(
            leads_since=datetime.combine(day, time.min).replace(
                tzinfo=db.scalar(select(AdAccount)).tzinfo()
            )
        )
    )
    db.commit()

    found = _read(db, owner)
    page = client.get(f"{CRM}/stats?period=7", headers=head).json()

    # $40 was spent before any lead could become a card: it brought none.
    assert found.totals.spend_minor == 1000
    assert sum(cell.spend_minor or 0 for cell in found.daily) == 1000
    assert page["sales"]["counted_since"] == day.isoformat()
    assert page["sales"]["pair"] == {
        "key": "page_1:act_1",
        "page": "Sahifa",
        "account": "Asosiy",
    }


def test_a_range_past_what_is_kept_has_no_spend_figure(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _spend(db, owner, "ad_1", "c_1", 10)
    db.execute(update(CrmSetup).values(leads_since=utcnow() - timedelta(days=300)))
    db.commit()
    viewer = selectors.viewer_for(db, user=db.get(User, owner.id), wanted="")
    today = _lead_day(db)

    def read(days: int) -> Stats:
        return stats(
            db,
            viewer=viewer,
            since=(today - timedelta(days=days)).isoformat(),
            until=today.isoformat(),
            now=utcnow(),
        )

    kept, past = read(170), read(200)

    assert answers(kept.totals)["spend"].value == 1000
    assert answers(past.totals)["spend"].missing == "not_kept"
    assert answers(past.totals)["cpl"].missing == "not_kept"
    # The leads are all there; only the spend is not whole.
    assert answers(past.totals)["leads"].value == 3
    assert answers(past.daily[-1])["spend"].missing == "not_kept"


def test_a_campaign_built_with_no_page_is_not_every_pairs_spend(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    account = db.scalar(select(AdAccount))
    assert account is not None
    # A launch on the account with no page named, a lead form on its advert,
    # and no lead of it on this board.
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            page_id=None,
            provider="meta",
            status="created",
            created_refs={"campaign": "c_free"},
        )
    )
    campaign = Campaign(
        owner_id=owner.id,
        provider="meta",
        external_id="c_free",
        ad_account_id=account.id,
    )
    db.add(campaign)
    db.flush()
    adset = AdSet(
        owner_id=owner.id,
        provider="meta",
        external_id="s_free",
        campaign_id=campaign.id,
    )
    db.add(adset)
    db.flush()
    db.add(
        Ad(
            owner_id=owner.id,
            provider="meta",
            external_id="ad_free",
            adset_id=adset.id,
            lead_form_external_id="f_other",
        )
    )
    db.commit()
    _spend(db, owner, "ad_1", "c_1", 10)
    _spend(db, owner, "ad_free", "c_free", 99)

    assert _read(db, owner).totals.spend_minor == 1000


def test_a_sale_in_one_currency_does_not_hide_the_spend_of_another(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    # Sold in dollars, then the CRM moves to so'm; the account pays in lira.
    assert client.post(
        f"{CRM}/cards/{card}/win", headers=head, json={"amount": "10"}
    ).is_success
    _som(client, head)
    db.execute(update(AdAccount).values(currency="TRY"))
    db.commit()
    day = _lead_day(db) - timedelta(days=5)
    db.add_all(
        [
            FxRate(day=day, currency="USD", rate=Decimal("12000")),
            FxRate(day=day, currency="TRY", rate=Decimal("300")),
        ]
    )
    db.add(
        MetricsDaily(
            owner_id=owner.id,
            provider="meta",
            external_id="ad_1",
            ad_account_id=db.scalar(select(AdAccount.id)),
            level="ad",
            campaign_external_id="c_1",
            date=_lead_day(db),
            spend_minor=50_000,
            currency="TRY",
            synced_at=utcnow(),
        )
    )
    db.commit()

    total = _read(db, owner).totals

    # 500 lira at 300 = 150 000 so'm; $10 at 12 000 = 120 000 so'm.
    assert (total.spend_minor, total.spend_gap) == (15_000_000, None)
    assert (total.revenue_minor, total.unpriced) == (12_000_000, 0)


def test_with_the_crm_switched_off_every_cut_says_so(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _spend(db, owner, "ad_1", "c_1", 10)
    off = client.post(f"{CRM}/settings/state", headers=head, json={"state": "off"})
    assert off.is_success, off.text

    found = _read(db, owner)

    cuts = [found.totals, found.earlier, *found.daily, *dict(found.ads).values()]
    assert cuts and all(
        {a.missing for a in answers(cut).values()} == {"no_crm"} for cut in cuts if cut
    )


def test_the_pages_old_list_of_adverts_is_still_the_ones_that_brought_leads(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _spend(db, owner, "ad_1", "c_1", 10)
    _spend(db, owner, "ad_2", "c_1", 5)

    page = client.get(f"{CRM}/stats?period=7", headers=head).json()

    assert [row["id"] for row in page["ads"]] == ["ad_1"]
    assert sorted(row["id"] for row in page["sales"]["ads"]) == ["ad_1", "ad_2"]


def test_a_dashboard_with_no_crm_reads_no_cards(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))

    sales = client.get("/api/v1/metrics/numbers?period=7", headers=head).json()["sales"]

    assert sales["state"] == "draft"
    assert sales["totals"]["leads"] == {"value": None, "missing": "no_crm"}
    assert sales["direct"]["leads"]["missing"] == "no_crm"


def test_a_lead_older_than_the_crms_first_day_brings_its_days_spend(
    client: TestClient, db: Session
) -> None:
    """A board switched on from a day still holds older leads (added by hand
    from the leads tab). They are counted as leads, so their days' spend is
    counted too: never leads against no spend."""
    from app.modules.crm.models import CrmCard
    from app.modules.leads.models import Lead

    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    day = _lead_day(db)
    zone = db.scalar(select(AdAccount)).tzinfo()
    _spend(db, owner, "ad_1", "c_1", 10)
    _spend(db, owner, "ad_1", "c_1", 40, day=day - timedelta(days=3))
    db.execute(
        update(CrmSetup).values(
            leads_since=datetime.combine(day, time.min).replace(tzinfo=zone)
        )
    )
    old = db.scalar(select(CrmCard.lead_id).limit(1))
    db.execute(
        update(Lead)
        .where(Lead.id == old)
        .values(submitted_at=utcnow() - timedelta(days=3, hours=2))
    )
    db.commit()

    found = _read(db, owner)
    page = client.get(f"{CRM}/stats?period=7", headers=head).json()

    # All three leads are counted, and so is the $40 of the oldest one's day.
    assert (found.totals.leads, found.totals.spend_minor) == (3, 5000)
    assert page["sales"]["counted_since"] == (day - timedelta(days=3)).isoformat()
    assert page["sales"]["totals"]["cpl"]["missing"] is None


def test_what_the_adverts_rows_miss_of_the_ad_sets_spend_is_the_campaigns(
    client: TestClient, db: Session
) -> None:
    """The dashboards sum the ad sets' rows; an advert's rows can lag behind
    them. With every advert counted the campaign's spend is its ad sets'."""
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    _spend(db, owner, "ad_1", "c_1", 10)
    _spend(db, owner, "as_1", "c_1", 15, level="adset")

    found = _read(db, owner)

    assert found.totals.spend_minor == 1500
    assert dict(found.campaigns)["c_1"].spend_minor == 1500
    # The $5 no advert's rows hold is nobody's line.
    assert dict(found.ads)["ad_1"].spend_minor == 1000
    assert sum(cell.spend_minor or 0 for cell in found.daily) == 1500

    # With ticked adverts the remainder cannot be told apart: left out.
    flow = {
        "since": "month",
        "every_ad": False,
        "ad": ["ad_1"],
        "offered": ["ad_1"],
        "take_new_ads": False,
    }
    assert client.post(f"{CRM}/settings/flow", headers=head, json=flow).is_success
    assert _read(db, owner).totals.spend_minor == 1000


def test_the_expert_rows_roas_is_the_crms_sales_in_the_accounts_currency(
    client: TestClient, db: Session
) -> None:
    from adskit import MinorUnits

    from app.modules.metrics.ranges import CUSTOM, Range
    from app.modules.metrics.selectors.expert import figures_by
    from core.metrics.catalogue import Setting, compute

    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    _som(client, head)
    _rate(db)
    _spend(db, owner, "as_1", "c_1", 10, level="adset")
    account = db.scalar(select(AdAccount))
    day = _lead_day(db)
    asked = Range(since=day - timedelta(days=6), until=day, key=CUSTOM)
    row = Setting(level="campaign", outcome="lead")

    def read() -> Any:
        db.expire_all()
        return figures_by(
            db,
            owner=db.get(User, owner.id),
            account=account,
            level="campaign",
            ids=["c_1"],
            date_range=asked,
        )["c_1"]

    # Leads and no sale closed: the reason, never 0.00.
    assert compute("roas", read(), row).missing == "no_sales"

    _sell(client, head, board)
    sold = read()

    # 600 000 so'm at 12 000 is $50, set against the $10 spent.
    assert (sold.purchases_crm, sold.sales_unpriced) == (1, 0)
    assert sold.purchase_value_crm_minor == MinorUnits(5_000)
    assert compute("roas", sold, row).value == Decimal("5.00")
