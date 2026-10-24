from dataclasses import dataclass, replace
from typing import Any

from adskit import MinorUnits

from app.common.money import format_minor
from app.modules.metrics.selectors.periods import CampaignMeta, money, screen_kind
from app.modules.metrics.selectors.results import note_for, words_for
from app.modules.metrics.selectors.shapes import OutcomeBlock
from core.metrics import Movement, Outcome, Totals, cost_per, movement, share

__all__ = ["outcomes"]
SLICES: int = 5


@dataclass(frozen=True, slots=True)
class _Tally:
    count: int = 0
    spend_minor: int = 0
    impressions: int = 0

    def plus(self, *, count: int, spend_minor: int, impressions: int) -> "_Tally":
        return _Tally(
            count=self.count + count,
            spend_minor=self.spend_minor + spend_minor,
            impressions=self.impressions + impressions,
        )


COMPARE_FLOOR = 5


def _kinds(
    *, keys: set[str], leads: dict[str, tuple[int, int]], names: dict[str, CampaignMeta]
) -> dict[str, Outcome]:
    everything = keys | set(leads)
    return {key: screen_kind(names.get(key)) for key in everything}


def campaigns_of(
    kind: Outcome,
    *,
    keys: set[str],
    leads: dict[str, tuple[int, int]],
    names: dict[str, CampaignMeta],
) -> frozenset[str]:
    everything = _kinds(keys=keys, leads=leads, names=names)
    return frozenset((key for key, one in everything.items() if one == kind))


def lead_reported(
    *,
    facts: dict[str, Any],
    leads: dict[str, tuple[int, int]],
    names: dict[str, CampaignMeta],
) -> tuple[int, int]:
    kinds = _kinds(keys=set(facts) | set(names), leads=leads, names=names)
    spend = reported = 0
    for key, kind in kinds.items():
        sums = facts.get(key)
        if kind == "lead" and sums is not None:
            spend += sums.spend_minor
            reported += sums.leads_reported
    return (spend, reported)


def _tally(
    *, kinds: dict[str, Outcome], facts: dict[str, Any]
) -> dict[Outcome, _Tally]:
    out: dict[Outcome, _Tally] = {}
    for key, kind in kinds.items():
        sums = facts.get(key)
        field = words_for(kind).field
        count = int(getattr(sums, field, 0) or 0) if sums and kind != "lead" else 0
        out[kind] = out.get(kind, _Tally()).plus(
            count=count,
            spend_minor=sums.spend_minor if sums else 0,
            impressions=int(getattr(sums, "impressions", 0) or 0) if sums else 0,
        )
    return out


def outcomes(
    *,
    facts: dict[str, Any],
    earlier: dict[str, Any],
    leads: dict[str, tuple[int, int]],
    names: dict[str, CampaignMeta],
    now: Totals,
    before: Totals,
    currency: str,
) -> tuple[OutcomeBlock, ...]:
    kinds = _kinds(
        keys=set(facts) | set(earlier) | set(names), leads=leads, names=names
    )
    tallies = _tally(kinds=kinds, facts=facts)
    was = _tally(kinds=kinds, facts=earlier)
    if "lead" in tallies:
        tallies["lead"] = _Tally(
            count=now.leads,
            spend_minor=tallies["lead"].spend_minor,
            impressions=tallies["lead"].impressions,
        )
        was["lead"] = _Tally(
            count=before.leads, spend_minor=was.get("lead", _Tally()).spend_minor
        )
    goals: dict[Outcome, set[str]] = {}
    for key, kind in kinds.items():
        meta = names.get(key)
        goals.setdefault(kind, set()).add(meta.goal if meta is not None else "")
    blocks = [
        _block(
            kind=kind,
            tally=tally,
            was=was.get(kind, _Tally()),
            goals=frozenset(goals.get(kind, set())),
            currency=currency,
        )
        for kind, tally in tallies.items()
    ]
    blocks.sort(key=lambda one: (-one.spend_minor, one.kind))
    return _with_shares(tuple(blocks))


def _with_shares(blocks: tuple[OutcomeBlock, ...]) -> tuple[OutcomeBlock, ...]:
    paid = sum(one.spend_minor for one in blocks)
    if paid:
        blocks = tuple(
            replace(one, spend_pct=share(part=one.spend_minor, whole=paid))
            for one in blocks
        )
    whole = sum(one.impressions for one in blocks)
    if not whole:
        return blocks
    out, running, colour = ([], 0, 0)
    for one in blocks:
        pct = share(part=one.impressions, whole=whole)
        if one.impressions:
            colour = min(colour + 1, SLICES)
        out.append(
            replace(
                one,
                shown_pct=pct,
                shown_before_pct=running,
                slice=colour if one.impressions else 0,
            )
        )
        running += pct
    return tuple(out)


def _block(
    *, kind: Outcome, tally: _Tally, was: _Tally, goals: frozenset[str], currency: str
) -> OutcomeBlock:
    text = words_for(kind)
    note = note_for(kind, optimization_goals=goals)
    moved = (
        movement(now=tally.count, before=was.count, lower_is_better=False)
        if was.count >= COMPARE_FLOOR
        else Movement()
    )
    return OutcomeBlock(
        kind=kind,
        label=text.label,
        cost_label=text.cost_label,
        hint=text.hint,
        headline_note=text.headline_note,
        count="" if note else f"{tally.count:,}".replace(",", " "),
        cost=""
        if note
        else money(
            cost_per(MinorUnits(tally.spend_minor * text.per), tally.count), currency
        ),
        spend=format_minor(amount_minor=tally.spend_minor, currency=currency),
        spend_minor=tally.spend_minor,
        shown=f"{tally.impressions:,}".replace(",", " "),
        impressions=tally.impressions,
        delta_pct=moved.percent,
        trend=moved.direction,
        is_good=moved.is_good,
        note=note,
    )
