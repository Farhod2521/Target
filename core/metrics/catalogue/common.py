"""The metrics every network has, each computed one way for all of them.

A network's spend, impressions and link clicks mean the same thing on Meta
and on Google, so a CPM or a CTR is one formula here. What only one network
measures lives in that network's module.
"""

from typing import Final

from core.metrics import formulas as f
from core.metrics import lead_count
from core.metrics.arithmetic import hundredths
from core.metrics.catalogue.spec import (
    Answer,
    Figures,
    Metric,
    Setting,
    cost,
    known,
    missing,
)
from core.metrics.formulas import RESULT_OF
from core.metrics.outcomes import Outcome

# Goals whose sale happens on the advertiser's website, where the pixel
# counts it. Every other goal's sale is the one the CRM marks won.
SITE_SALE_GOALS: Final[frozenset[Outcome]] = frozenset({"site_lead", "click", "none"})


def leads(figures: Figures, setting: Setting) -> int:
    """The lead count to show and to price by - see :mod:`core.metrics.lead_count`."""
    if setting.outcome == "site_lead":
        return figures.leads_reported
    return lead_count.counted_leads(
        ours=figures.leads_ours,
        reported=figures.leads_reported,
        measured=figures.read
        and lead_count.measured(
            spend_minor=figures.spend_minor,
            impressions=figures.impressions,
            reported=figures.leads_reported,
        ),
    )


def result_count(figures: Figures, setting: Setting) -> int | None:
    found = RESULT_OF.get(setting.outcome)
    if found is None:
        return None
    name, _ = found
    return leads(figures, setting) if name == "leads" else int(getattr(figures, name))


def _spend(figures: Figures, setting: Setting) -> Answer:
    return Answer(value=figures.spend_minor)


def _results(figures: Figures, setting: Setting) -> Answer:
    count = result_count(figures, setting)
    return missing("uncounted") if count is None else Answer(value=count)


def _cost_per_result(figures: Figures, setting: Setting) -> Answer:
    count = result_count(figures, setting)
    if count is None:
        return missing("uncounted")
    per = f.result_per(setting.outcome)
    return cost(
        f.cost_per_result(figures.spend_minor, count, per=per),
        spend_minor=figures.spend_minor,
    )


def _impressions(figures: Figures, setting: Setting) -> Answer:
    return Answer(value=figures.impressions)


def _cpm(figures: Figures, setting: Setting) -> Answer:
    return cost(
        f.cpm(figures.spend_minor, figures.impressions),
        spend_minor=figures.spend_minor,
    )


def _links(figures: Figures, setting: Setting) -> Answer | None:
    """``no_link`` for a messaging campaign, whose clicks open a chat."""
    return missing("no_link") if setting.outcome == "chat" else None


def _link_clicks(figures: Figures, setting: Setting) -> Answer:
    return _links(figures, setting) or Answer(value=figures.link_clicks)


def _ctr(figures: Figures, setting: Setting) -> Answer:
    return _links(figures, setting) or known(
        hundredths(f.ctr(figures.link_clicks, figures.impressions))
    )


def _cpc(figures: Figures, setting: Setting) -> Answer:
    return _links(figures, setting) or cost(
        f.cpc(figures.spend_minor, figures.link_clicks),
        spend_minor=figures.spend_minor,
    )


def _leads(figures: Figures, setting: Setting) -> Answer:
    return Answer(value=leads(figures, setting))


def _form_conversion(figures: Figures, setting: Setting) -> Answer:
    """Leads over the step before them: the click on an instant form, the
    page view on a website."""
    if setting.outcome == "lead":
        return known(
            hundredths(f.form_conversion(leads(figures, setting), figures.link_clicks))
        )
    if setting.outcome == "site_lead":
        return known(
            hundredths(
                f.form_conversion(leads(figures, setting), figures.landing_page_views)
            )
        )
    return missing("no_link") if setting.outcome == "chat" else missing("other_goal")


def _qualified(figures: Figures, setting: Setting) -> Answer:
    return Answer(value=figures.qualified)


def _qualified_share(figures: Figures, setting: Setting) -> Answer:
    """Over our own leads: the qualified ones are a subset of those, and the
    network's count may hold leads that never reached the CRM."""
    return known(hundredths(f.qualified_share(figures.qualified, figures.leads_ours)))


def _cpql(figures: Figures, setting: Setting) -> Answer:
    return cost(
        f.cpql(figures.spend_minor, figures.qualified),
        spend_minor=figures.spend_minor,
    )


def _purchases_site(figures: Figures, setting: Setting) -> Answer:
    return Answer(value=figures.purchases_site)


def _purchases_crm(figures: Figures, setting: Setting) -> Answer:
    return Answer(value=figures.purchases_crm)


def sales(figures: Figures, setting: Setting) -> int:
    """The sales a campaign is priced by: the pixel's for a website goal,
    the CRM's for everything else. Never both - one buyer can be in each."""
    if setting.outcome in SITE_SALE_GOALS:
        return figures.purchases_site
    return figures.purchases_crm


def _cost_per_purchase(figures: Figures, setting: Setting) -> Answer:
    if setting.outcome not in SITE_SALE_GOALS and not figures.crm:
        return missing("no_crm")
    return cost(
        f.cost_per_purchase(figures.spend_minor, sales(figures, setting)),
        spend_minor=figures.spend_minor,
    )


def _purchase_value(figures: Figures, setting: Setting) -> Answer:
    return Answer(value=figures.purchase_value_site_minor)


def _roas(figures: Figures, setting: Setting) -> Answer:
    if figures.spend_minor <= 0:
        return missing("no_spend")
    return known(
        hundredths(f.roas(figures.purchase_value_site_minor, figures.spend_minor))
    )


COMMON: Final[tuple[Metric, ...]] = (
    Metric(
        key="spend",
        label="Sarflandi",
        hint="Reklama uchun sarflangan pul.",
        group="money",
        unit="money",
        formula=_spend,
    ),
    Metric(
        key="results",
        label="Natija",
        hint="Kampaniya maqsadi bo'yicha natija: lid, suhbat, o'tish yoki ko'rish.",
        group="result",
        unit="count",
        formula=_results,
    ),
    Metric(
        key="cost_per_result",
        label="Bittasi",
        hint="Bitta natija narxi: Sarflandi ÷ Natija. Ko'rish maqsadida 1000 ko'rish narxi.",
        group="money",
        unit="money",
        formula=_cost_per_result,
        lower_is_better=True,
    ),
    Metric(
        key="impressions",
        label="Ko'rsatildi",
        hint="Reklama necha marta ekranga chiqdi.",
        group="delivery",
        unit="count",
        formula=_impressions,
    ),
    Metric(
        key="cpm",
        label="CPM",
        hint="1000 ko'rsatish narxi: Sarflandi ÷ Ko'rsatildi × 1000.",
        group="money",
        unit="money",
        formula=_cpm,
        lower_is_better=True,
    ),
    Metric(
        key="link_clicks",
        label="Link kliklar",
        hint="Reklamadagi havolani bosganlar.",
        group="engagement",
        unit="count",
        formula=_link_clicks,
    ),
    Metric(
        key="ctr",
        label="CTR",
        hint="Link kliklar ÷ Ko'rsatildi × 100%.",
        group="engagement",
        unit="percent",
        formula=_ctr,
    ),
    Metric(
        key="cpc",
        label="CPC",
        hint="Bitta link klik narxi: Sarflandi ÷ Link kliklar.",
        group="money",
        unit="money",
        formula=_cpc,
        lower_is_better=True,
    ),
    Metric(
        key="leads",
        label="Lidlar",
        hint="Formani to'ldirganlar. Meta sanagan son; Meta hali o'qimagan kunlarda bizniki.",
        group="result",
        unit="count",
        formula=_leads,
        from_network=False,
    ),
    Metric(
        key="form_conversion",
        label="Forma konversiyasi",
        hint="Instant forma: Lidlar ÷ Link kliklar. Sayt: Lidlar ÷ Sahifaga o'tishlar.",
        group="result",
        unit="percent",
        formula=_form_conversion,
    ),
    Metric(
        key="qualified",
        label="Sifatli lid",
        hint="CRM'da sifatli deb belgilangan lidlar.",
        group="quality",
        unit="count",
        formula=_qualified,
        from_network=False,
        from_crm=True,
    ),
    Metric(
        key="qualified_share",
        label="Sifatli lid %",
        hint="Sifatli lid ÷ bizga kelgan lidlar × 100%.",
        group="quality",
        unit="percent",
        formula=_qualified_share,
        from_network=False,
        from_crm=True,
    ),
    Metric(
        key="cpql",
        label="Sifatli lid narxi",
        hint="Sarflandi ÷ Sifatli lid.",
        group="quality",
        unit="money",
        formula=_cpql,
        lower_is_better=True,
        from_crm=True,
    ),
    Metric(
        key="purchases_site",
        label="Sotuv (sayt)",
        hint="Saytdagi pixel sanagan xaridlar.",
        group="sales",
        unit="count",
        formula=_purchases_site,
    ),
    Metric(
        key="purchases_crm",
        label="Sotuv (CRM)",
        hint="CRM'da sotildi deb belgilangan lidlar.",
        group="sales",
        unit="count",
        formula=_purchases_crm,
        from_network=False,
        from_crm=True,
    ),
    Metric(
        key="cost_per_purchase",
        label="Sotuv narxi",
        hint="Sarflandi ÷ Sotuvlar. Sayt maqsadida pixel sotuvlari, qolganlarida CRM sotuvlari.",
        group="sales",
        unit="money",
        formula=_cost_per_purchase,
        lower_is_better=True,
    ),
    Metric(
        key="purchase_value",
        label="Sotuv summasi",
        hint="Saytdagi pixel yuborgan xaridlar summasi.",
        group="sales",
        unit="money",
        formula=_purchase_value,
    ),
    Metric(
        key="roas",
        label="ROAS",
        hint="Sotuv summasi ÷ Sarflandi. 3 bo'lsa, sarflangan har 1 birlik pul 3 birlik sotuv keltirgan.",
        group="sales",
        unit="ratio",
        formula=_roas,
    ),
)

__all__ = [
    "COMMON",
    "SITE_SALE_GOALS",
    "leads",
    "result_count",
    "sales",
]
