"""Advertising set against the sales it brought: one set of figures, one
set of answers.

Marketing knows what was spent and how many leads came; the sales side
knows which of them bought and for how much. :class:`SalesFigures` holds
both for one group of leads - a period, a campaign, an advert, a manager, a
day - and :func:`answers` is every metric built on them. A screen, a report
or a rule asks here and nowhere else, so ROAS on the dashboard is the ROAS
of the CRM page.

**One group of people.** The leads are the ones that arrived in the range,
and every count after them - taken, qualified, sold, the revenue - is of
those same leads, whenever the sale closed. The spend is the range's. So a
lead of the 3rd sold on the 20th is a sale of the 3rd's money, the
conversion never passes 100%, and ROAS sets a period's spend against what
that spend brought. A recent range reads low until its leads are worked
through: :func:`completeness` says how far that is.

**One currency.** Every amount is in the CRM's currency. The spend is
crossed from the ad account's at each day's rate and a sale written in
another currency at its closing day's rate. What no rate could price is
counted (``spend_unpriced_days``, ``unpriced``) and the sum it is missing
from answers nothing: a figure with a hole in it is wrong, not small.

**Never a nought for "not known".** With the CRM off, with no sale closed
yet, with nothing spent, an answer carries the reason in place of a value.
"""

from dataclasses import dataclass, field
from typing import Final, Literal

from adskit import MinorUnits

from core.metrics import formulas as f
from core.metrics.arithmetic import hundredths
from core.metrics.catalogue.spec import Answer, Missing, cost, known, missing

SalesUnit = Literal["money", "count", "percent", "ratio", "minutes"]

# Under this share of the leads looked at, the sales figures describe the
# sellers' backlog more than the advertising.
HANDLED_FLOOR_PCT: Final = 50

Level = Literal["off", "empty", "low", "ok"]


@dataclass(slots=True)
class SalesFigures:
    """What one group of leads cost and what became of them."""

    # Advertising spend of the range, in the CRM's currency. ``None`` where
    # the group has no spend of its own: a manager is not an advert.
    spend_minor: int | None = 0
    # Days whose spend no rate could price; their money is not in the sum.
    spend_unpriced_days: int = 0
    # Why the spend is not whole, if it is not: ``no_rate`` (days no rate
    # prices) or ``not_kept`` (the range reaches past what is kept). A sum
    # with a hole in it prices nothing: every answer built on it is missing.
    spend_gap: Missing | None = None
    leads: int = 0
    # A manager holds the card.
    taken: int = 0
    # Somebody moved the card on from the first column.
    judged: int = 0
    qualified: int = 0
    won: int = 0
    lost: int = 0
    junk: int = 0
    revenue_minor: int = 0
    # Sales no rate could price; their money is not in the revenue.
    unpriced: int = 0
    # Minutes from the lead arriving to a manager taking it.
    waits: list[float] = field(default_factory=list)
    # Minutes from the lead arriving to the sale closing, sold cards only.
    deals: list[float] = field(default_factory=list)
    # Whether a CRM is on for these leads at all.
    crm: bool = True

    @property
    def closed(self) -> int:
        return self.won + self.lost + self.junk

    @property
    def open(self) -> int:
        """Still being worked: a sale may yet come from these."""
        return max(self.leads - self.closed, 0)

    @property
    def priced_sales(self) -> int:
        return max(self.won - self.unpriced, 0)


@dataclass(frozen=True, slots=True)
class SalesMetric:
    key: str
    label: str
    hint: str
    unit: SalesUnit
    lower_is_better: bool = False


SALES: Final[tuple[SalesMetric, ...]] = (
    SalesMetric(
        "spend",
        "Sarflandi",
        "CRM'ga lid beradigan reklamalarga shu davrda sarflangan pul, CRM valyutasida.",
        "money",
    ),
    SalesMetric(
        "revenue",
        "Daromad",
        "Shu davrda kelgan lidlardan CRM'da yopilgan sotuvlar summasi.",
        "money",
    ),
    SalesMetric(
        "roas",
        "ROAS",
        "Daromad ÷ Sarflandi. 3 bo'lsa, reklamaga sarflangan pul 3 baravar sotuv keltirgan.",
        "ratio",
    ),
    SalesMetric(
        "cac",
        "Mijoz narxi (CAC)",
        "Sarflandi ÷ Sotuvlar soni: bitta mijozni olish reklamada qanchaga tushgani.",
        "money",
        lower_is_better=True,
    ),
    SalesMetric(
        "cpl",
        "Lid narxi",
        "Sarflandi ÷ Lidlar soni.",
        "money",
        lower_is_better=True,
    ),
    SalesMetric(
        "cpql",
        "Sifatli lid narxi",
        "Sarflandi ÷ Sifatli lidlar soni.",
        "money",
        lower_is_better=True,
    ),
    SalesMetric("leads", "Lidlar", "Shu davrda CRM'ga tushgan lidlar.", "count"),
    SalesMetric(
        "qualified", "Sifatli lidlar", "CRM'da sifatli deb topilgan lidlar.", "count"
    ),
    SalesMetric("sales", "Sotuvlar", "CRM'da sotildi deb yopilgan lidlar.", "count"),
    SalesMetric(
        "conversion",
        "Konversiya",
        "Sotuvlar ÷ Lidlar × 100%: lidlarning qancha qismi sotuvga aylangani.",
        "percent",
    ),
    SalesMetric(
        "qualified_share",
        "Sifatli lid %",
        "Sifatli lidlar ÷ Lidlar × 100%.",
        "percent",
    ),
    SalesMetric(
        "close_rate",
        "Yopish darajasi",
        "Sotuvlar ÷ Sifatli lidlar × 100%: sotuv bo'limi sifatli lidning qanchasini yopgani.",
        "percent",
    ),
    SalesMetric(
        "avg_deal",
        "O'rtacha chek",
        "Daromad ÷ Sotuvlar soni.",
        "money",
    ),
    SalesMetric(
        "deal_time",
        "Bitim muddati",
        "Lid kelganidan sotuv yopilguncha o'tgan vaqt: sotuvlarning o'rtadagisi (mediana).",
        "minutes",
        lower_is_better=True,
    ),
    SalesMetric(
        "first_response",
        "Birinchi javob",
        "Lid kelganidan menejer olguncha o'tgan vaqt (mediana).",
        "minutes",
        lower_is_better=True,
    ),
)

SALES_KEYS: Final[tuple[str, ...]] = tuple(metric.key for metric in SALES)
# The answers that need the advertising's spend.
_OF_SPEND: Final = frozenset({"spend", "roas", "cac", "cpl", "cpql"})


def _money(value: int | None) -> Answer:
    return Answer(value=MinorUnits(value)) if value is not None else missing("no_base")


def answers(figures: SalesFigures) -> dict[str, Answer]:
    """Every sales metric of one group, or why it has none."""
    if not figures.crm:
        return {key: missing("no_crm") for key in SALES_KEYS}
    spend = figures.spend_minor
    sold = figures.won > 0
    found: dict[str, Answer] = {
        "leads": Answer(value=figures.leads),
        "qualified": Answer(value=figures.qualified),
        "sales": Answer(value=figures.won),
        "qualified_share": known(
            hundredths(f.qualified_share(figures.qualified, figures.leads))
        ),
        "first_response": known(f.typical_minutes(figures.waits)),
    }
    # With no sale closed, revenue is unknown and not nought: the leads may
    # be sold and nobody has said so in the CRM.
    if not sold:
        unsold = missing("no_sales" if figures.leads else "no_base")
        for key in ("revenue", "roas", "cac", "avg_deal", "deal_time"):
            found[key] = unsold
        found["conversion"] = known(
            hundredths(f.sale_conversion(figures.won, figures.leads))
        )
        found["close_rate"] = known(
            hundredths(f.close_rate(figures.won, figures.qualified))
        )
    else:
        # A sale no rate prices is money missing from the revenue: the sum
        # would be wrong, not small.
        found["revenue"] = (
            missing("no_rate") if figures.unpriced else _money(figures.revenue_minor)
        )
        found["conversion"] = known(
            hundredths(f.sale_conversion(figures.won, figures.leads))
        )
        found["close_rate"] = known(
            hundredths(f.close_rate(figures.won, figures.qualified))
        )
        found["avg_deal"] = known(
            f.average_deal(figures.revenue_minor, figures.priced_sales)
        )
        found["deal_time"] = known(f.typical_minutes(figures.deals))
    if spend is None:
        for key in _OF_SPEND:
            found[key] = missing("not_here")
        return found
    if figures.spend_gap is not None:
        for key in _OF_SPEND:
            found[key] = missing(figures.spend_gap)
        return found
    found["spend"] = Answer(value=MinorUnits(spend))
    found["cpl"] = cost(f.cpl(spend, figures.leads), spend_minor=spend)
    found["cpql"] = cost(f.cpql(spend, figures.qualified), spend_minor=spend)
    if sold:
        found["cac"] = cost(f.cac(spend, figures.won), spend_minor=spend)
        if figures.unpriced:
            found["roas"] = missing("no_rate")
        elif spend <= 0:
            found["roas"] = missing("no_spend")
        else:
            found["roas"] = known(hundredths(f.roas(figures.revenue_minor, spend)))
    return found


@dataclass(frozen=True, slots=True)
class Completeness:
    """How far the CRM has worked through a group's leads - how much the
    sales figures can be trusted yet."""

    level: Level
    # Leads somebody moved on from the first column, of all leads.
    handled_pct: int
    # Leads closed one way or another - sold, refused, junk - of all leads.
    closed_pct: int
    # Leads still open: a sale may yet come from these.
    open: int
    note: str


def completeness(figures: SalesFigures) -> Completeness:
    if not figures.crm:
        return Completeness("off", 0, 0, 0, "CRM yoqilmagan: sotuv ma'lumoti yo'q.")
    if not figures.leads:
        return Completeness("empty", 0, 0, 0, "Bu davrda CRM'ga lid tushmagan.")
    handled = f.lead_share(figures.judged, figures.leads)
    closed = f.lead_share(figures.closed, figures.leads)
    handled_pct = round(handled) if handled is not None else 0
    closed_pct = round(closed) if closed is not None else 0
    if handled_pct < HANDLED_FLOOR_PCT:
        waiting = figures.leads - figures.judged
        return Completeness(
            "low",
            handled_pct,
            closed_pct,
            figures.open,
            f"{waiting} ta lid hali ko'rib chiqilmagan. Sotuv raqamlari to'liq emas: "
            "lidlarni CRM'da olib, natijasini belgilang.",
        )
    note = (
        f"{figures.open} ta lid hali ishlanmoqda: ulardan sotuv kelsa, raqamlar o'sadi."
        if figures.open
        else ""
    )
    return Completeness("ok", handled_pct, closed_pct, figures.open, note)


__all__ = [
    "HANDLED_FLOOR_PCT",
    "SALES",
    "SALES_KEYS",
    "Completeness",
    "SalesFigures",
    "SalesMetric",
    "answers",
    "completeness",
]
