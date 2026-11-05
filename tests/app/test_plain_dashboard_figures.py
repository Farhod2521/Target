"""The plain dashboard's sums and shares, which the browser used to work out."""

from app.modules.metrics.constants import TOP_CAMPAIGNS
from app.modules.metrics.selectors import chart, periods
from app.modules.metrics.selectors.lead_quality import level_of
from app.modules.metrics.selectors.shapes import CampaignRow, KindView


def _row(name: str, *, kind: str, spend: int, results: int = 0, **more) -> CampaignRow:
    fields = {
        "name": name,
        "delivery": "active",
        "delivery_label": "",
        "spend": "",
        "spend_minor": spend,
        "leads": 0,
        "qualified": 0,
        "cpl": "",
        "cpql": "",
        "note": "",
        "results": results,
        "kind": kind,
    } | more
    return CampaignRow(**fields)


def test_a_group_sums_every_campaign_not_only_the_listed_top() -> None:
    rows = [
        _row(f"c{n}", kind="chat", spend=1000, results=2)
        for n in range(TOP_CAMPAIGNS + 4)
    ]

    (group,) = periods.groups(rows, currency="USD")

    assert group.campaigns == TOP_CAMPAIGNS + 4
    assert group.spend_minor == 1000 * (TOP_CAMPAIGNS + 4)
    assert group.results == 2 * (TOP_CAMPAIGNS + 4)
    assert group.cost_minor == 500
    assert group.qualified_pct is None


def test_a_view_is_priced_per_thousand_and_an_uncounted_kind_has_no_cost() -> None:
    rows = [
        _row("v", kind="view", spend=3000, results=2000),
        _row("x", kind="none", spend=9000, results=5),
    ]

    none, view = periods.groups(rows, currency="USD")

    assert (view.kind, view.cost_minor) == ("view", 1500)
    assert (none.kind, none.counted, none.results, none.cost_minor) == (
        "none",
        False,
        0,
        None,
    )


def test_lead_quality_is_of_the_results_or_of_our_leads_when_meta_has_none() -> None:
    rows = [
        _row("a", kind="lead", spend=100, results=10, leads=10, qualified=3),
        _row("b", kind="lead", spend=100, results=0, leads=5, qualified=1),
    ]

    (group,) = periods.groups(rows, currency="USD")

    assert group.results == 15
    assert group.qualified_pct == 26.7


def _view(kind: str, spends: list[int]) -> KindView:
    line = chart.series(
        key="spend",
        label="",
        values=spends,
        labels=[""] * len(spends),
        displays=[""] * len(spends),
    )
    return KindView(kind=kind, label="", series=(line,), funnel=())


def test_each_day_is_split_between_the_kinds() -> None:
    totals, (lead, chat) = periods.split(
        [_view("lead", [300, 0]), _view("chat", [100, 0])]
    )

    assert totals == (400, 0)
    assert lead.spend_share == (75.0, None)
    assert chat.spend_share == (25.0, None)


def test_the_lead_quality_card_level() -> None:
    def level(**given):
        return level_of(
            **(
                {
                    "crm": True,
                    "problem": "none",
                    "marked_pct": 50.0,
                    "qualified_pct": 10.0,
                }
                | given
            )
        )

    assert level(crm=False) == "off"
    assert level(problem="no_pixel") == "no_pixel"
    assert level(marked_pct=29.9) == "unused"
    assert level(qualified_pct=4.9) == "low"
    assert level() == "ok"


def test_a_lead_row_meta_reports_nothing_for_is_priced_by_our_leads() -> None:
    from app.modules.metrics.selectors.periods import CampaignMeta, campaigns

    sums = type("Sums", (), {"spend_minor": 611})()
    (row,) = campaigns(
        facts={"c1": sums},
        leads={"c1": (10, 2)},
        names={
            "c1": CampaignMeta(
                name="Ariza",
                delivery="active",
                delivery_label="",
                kind="lead",
                goal="LEAD_GENERATION",
            )
        },
        currency="USD",
    )

    assert (row.results, row.result_cost_minor, row.qualified_pct) == (0, 61, 20.0)
