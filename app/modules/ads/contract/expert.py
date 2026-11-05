"""The expert table: every level's rows with every metric the catalogue has.

The rows are the manager's - names, statuses, budgets, controls, problems -
with the figures it computed itself taken off. In their place each row has
a cell per metric that exists at its level and network: the value the
catalogue computed, or the reason there is none. The screen formats; it
never divides.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable
from decimal import Decimal
from typing import Any, Final, cast

from metaads.insights import ATTRIBUTION_ASKED
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.contract.figures_v2 import _by_account, _campaigns_by_id
from app.modules.ads.contract.listing import ListAsk, figures_range
from app.modules.ads.contract.manager import manager
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.selectors.expert import (
    differing_attribution,
    figures_by,
    last_read_on,
    outcome_of_adsets,
    whole_account_people,
)
from app.modules.metrics.selectors.facts import People
from core.metrics.catalogue import (
    BY_KEY,
    MISSING_WORDS,
    Answer,
    Figures,
    Level,
    Setting,
    add_up,
    compute,
    metrics_for,
)
from core.metrics.outcomes import Outcome

# What the manager computed for itself and the expert table does not show.
DROPPED: Final = (
    "results",
    "unit_cost",
    "spent",
    "impressions",
    "reach",
    "clicks",
    "result_label",
)
LEVELS: Final = (
    (MetricLevel.CAMPAIGN, "campaigns"),
    (MetricLevel.ADSET, "adsets"),
    (MetricLevel.AD, "ads"),
)


def cell(answer: Answer) -> dict[str, Any]:
    value = answer.value
    if isinstance(value, Decimal):
        value = float(value)
    return {"value": value, "missing": answer.missing}


def cells(figures: Figures, setting: Setting) -> dict[str, dict[str, Any]]:
    return {
        metric.key: cell(compute(metric.key, figures, setting))
        for metric in metrics_for(level=setting.level, network=setting.network)
    }


def _network(provider: str) -> Any:
    return provider if provider in ("meta", "google", "chatgpt") else "meta"


def expert_table(
    db: Session,
    *,
    owner: User,
    ask: ListAsk,
    campaigns: Collection[str] = (),
    adsets: Collection[str] = (),
) -> dict[str, Any]:
    """Every level's rows and cells. ``campaigns`` and ``adsets`` narrow the
    levels under them, as ticking rows does on the screen, so each level's
    total is the total of the rows it shows."""
    # Its figures are the catalogue's, read below; the manager's own are not asked.
    out = manager(db, owner=owner, ask=ask, counted=False)
    if campaigns:
        keep = set(campaigns)
        for name in ("adsets", "ads"):
            out[name] = [
                row for row in out[name] if row["campaign_external_id"] in keep
            ]
    if adsets:
        keep = set(adsets)
        out["ads"] = [row for row in out["ads"] if row.get("adset_external_id") in keep]
    campaigns = _campaigns_by_id(
        db, owner=owner, ids=[row["campaign_external_id"] for row in out["campaigns"]]
    )
    groups = {
        group.external_id: group
        for campaign in campaigns.values()
        for group in campaign.adsets
    }
    outcome_of: dict[str, Outcome] = {
        external_id: outcome_of_adsets(campaign.adsets)
        for external_id, campaign in campaigns.items()
    }
    group_outcome: dict[str, Outcome] = {
        external_id: outcome_of_adsets([group]) for external_id, group in groups.items()
    }
    totals: dict[str, list[tuple[Figures, Outcome, str, Any]]] = defaultdict(list)
    # Each level's people counted by the network, account by account.
    people: dict[str, list[People | None]] = defaultdict(list)
    ranges = []
    for account, members in _by_account(campaigns.values()).items():
        chosen, _ = figures_range(db, owner=owner, account=account, ask=ask)
        ranges.append(chosen)
        here = {campaign.external_id for campaign in members}
        network = _network(account.provider)
        for level, name in LEVELS:
            rows = [row for row in out[name] if row["campaign_external_id"] in here]
            ids = [row["id"] for row in rows]
            figures = figures_by(
                db,
                owner=owner,
                account=account,
                level=level,
                ids=ids,
                date_range=chosen,
            )
            people[name].append(
                whole_account_people(
                    db,
                    owner=owner,
                    account=account,
                    level=level,
                    ids=ids,
                    date_range=chosen,
                )
            )
            for row in rows:
                outcome: Outcome = (
                    group_outcome.get(row["id"], "lead")
                    if level == MetricLevel.ADSET
                    else group_outcome.get(row.get("adset_external_id") or "")
                    or outcome_of.get(row["campaign_external_id"], "lead")
                )
                own = figures.get(row["id"], Figures())
                setting = Setting(
                    level=cast(Level, str(level)), network=network, outcome=outcome
                )
                for dropped in DROPPED:
                    row.pop(dropped, None)
                row["outcome"] = outcome
                row["currency"] = account.currency
                row["cells"] = cells(own, setting)
                totals[name].append((own, outcome, account.currency, network))
    accounts = [campaign.ad_account for campaign in campaigns.values()]
    since = min((one.since for one in ranges), default=None)
    until = max((one.until for one in ranges), default=None)
    return {
        **out,
        "totals": {
            name: _total(totals[name], level=str(level), people=people[name])
            for level, name in LEVELS
        },
        "range": {"since": since, "until": until},
        "synced_at": last_read_on(db, accounts=accounts),
        "attribution": {
            "asked": ATTRIBUTION_ASKED,
            "differs": since is not None
            and until is not None
            and differing_attribution(db, accounts=accounts, since=since, until=until),
        },
    }


def _total(
    rows: list[tuple[Figures, Outcome, str, Any]],
    *,
    level: str,
    people: list[People | None],
) -> dict[str, Any]:
    outcomes = {outcome for _, outcome, _, _ in rows}
    currencies = {currency for _, _, currency, _ in rows}
    networks = {network for _, _, _, network in rows}
    setting = Setting(
        level=level,  # type: ignore[arg-type]
        network=next(iter(networks)) if len(networks) == 1 else "meta",
        outcome=next(iter(outcomes)) if len(outcomes) == 1 else "lead",
        mixed=len(outcomes) > 1,
    )
    # One account's alone: two accounts may reach the same person.
    whole = people[0] if len(people) == 1 else None
    total = add_up(
        [figures for figures, _, _, _ in rows],
        currencies=len(currencies),
        reach=whole.reach if whole else None,
        unique_link_clicks=whole.unique_link_clicks if whole else None,
    )
    return {
        "count": len(rows),
        "currency": next(iter(currencies)) if len(currencies) == 1 else None,
        "cells": cells(total, setting),
    }


# -- the columns ----------------------------------------------------------------------

# Ready-made sets of columns, as the expert reads a campaign: at a glance,
# its video, the quality of its leads, its sales.
PRESETS: Final[dict[str, tuple[str, ...]]] = {
    "general": (
        "spend",
        "results",
        "cost_per_result",
        "reach",
        "impressions",
        "frequency",
        "cpm",
        "link_clicks",
        "ctr",
        "cpc",
    ),
    "video": (
        "spend",
        "impressions",
        "hook_rate",
        "hold_rate",
        "ctr",
        "cpc",
        "results",
        "cost_per_result",
    ),
    "quality": (
        "spend",
        "leads",
        "form_conversion",
        "qualified",
        "qualified_share",
        "cpql",
        "quality_ranking",
        "engagement_rate_ranking",
        "conversion_rate_ranking",
    ),
    "sales": (
        "spend",
        "purchases_site",
        "purchases_crm",
        "cost_per_purchase",
        "purchase_value",
        "roas",
    ),
}
PRESET_LABELS: Final[dict[str, str]] = {
    "general": "Umumiy",
    "video": "Video",
    "quality": "Lid sifati",
    "sales": "Sotuv",
}


def _column(metric: Any) -> dict[str, Any]:
    return {
        "key": metric.key,
        "label": metric.label,
        "hint": metric.hint,
        "group": metric.group,
        "unit": metric.unit,
        "lower_is_better": metric.lower_is_better,
        "norm": metric.norm,
    }


def chosen_columns(db: Session, *, owner: User) -> list[str]:
    from sqlalchemy import select

    from app.modules.metrics.models import MetricPreference

    stored = db.scalar(
        select(MetricPreference.expert_chosen).where(
            MetricPreference.owner_id == owner.id
        )
    )
    # Until the owner picks, the general set: every column at once is too wide to read.
    if not isinstance(stored, list):
        return list(PRESETS["general"])
    return [key for key in stored if key in BY_KEY]


def save_columns(db: Session, *, owner: User, keys: Iterable[str]) -> list[str]:
    from sqlalchemy import select

    from app.modules.metrics.models import MetricPreference

    seen: list[str] = []
    for key in keys:
        if key in BY_KEY and key not in seen:
            seen.append(key)
    row = db.scalars(
        select(MetricPreference).where(MetricPreference.owner_id == owner.id)
    ).first()
    if row is None:
        row = MetricPreference(owner_id=owner.id, chosen=[])
        db.add(row)
    row.expert_chosen = seen
    db.flush()
    return seen


def columns(db: Session, *, owner: User, network: str = "meta") -> dict[str, Any]:
    net = _network(network)
    return {
        "levels": {
            name: [_column(m) for m in metrics_for(level=str(level), network=net)]  # type: ignore[arg-type]
            for level, name in LEVELS
        },
        "chosen": chosen_columns(db, owner=owner),
        "presets": [
            {"key": key, "label": PRESET_LABELS[key], "columns": list(keys)}
            for key, keys in PRESETS.items()
        ],
        "missing": dict(MISSING_WORDS),
    }


__all__ = [
    "PRESETS",
    "cell",
    "cells",
    "chosen_columns",
    "columns",
    "expert_table",
    "save_columns",
]
