"""Everything a strategy is allowed to look at, as plain values.

The ``facts.py`` of this package. Nothing here queries anything: the
Django layer assembles one :class:`StrategyState` from the tables it
already keeps - the metrics, the audience mirror, the launch answers - and
the playbook reasons about the value. The same discipline as
``core.agent.facts``, bought for the same reason: a recommendation can be
replayed months later from the state that produced it.

What the account holds arrives here as counts and postures, not as rows. A
strategy does not need the audiences - it needs to know whether a usable
seed exists; it does not need the launch draft - it needs to know which
mode the ad set was chosen in. Narrowing at the boundary is what keeps the
playbook readable and the assembly honest about what is actually consumed.
"""

from dataclasses import dataclass

from core.strategy.lifecycle import LifecycleStage
from core.strategy.maturity import SignalHistory
from core.targeting import PlacementMode, TargetingMode


@dataclass(frozen=True, slots=True)
class AudienceAssets:
    """What the account holds at the provider, counted rather than listed.

    Counts, because every question the playbook asks is "is there one" or
    "is there none yet" - and a count answers both while staying small
    enough to store beside the advice it produced.
    """

    # Audiences a lookalike could be built from *today*: seedable, ready,
    # and counted by the provider. The three conditions are applied where
    # the rows are read rather than re-derived here.
    ready_seeds: int = 0
    # Audiences already built to resemble another. One is enough to stop
    # proposing the first lookalike; refreshing an ageing one is a
    # separate question.
    lookalikes: int = 0
    # Rule-built gatherers - site visitors, page engagers, form openers -
    # whether this product created them or somebody built one in the
    # provider's console. Either way the retargeting strategy is done.
    retargeting: int = 0
    # Whether anything exists to build retargeting *from*: a pixel, a
    # connected page, a lead form. Without one the strategy is not
    # "build an audience", it is "get a source first" - and the advice
    # says which.
    has_traffic_source: bool = False


@dataclass(frozen=True, slots=True)
class AdSetPosture:
    """One ad set, as much of it as a strategy reads.

    Deliberately not :class:`core.agent.AdSetFacts`. That value carries a
    week of figures for judging performance; this one carries standing -
    what stage it is in, how it was aimed, how many creatives compete in
    it. A strategy never reads a cost from here, and keeping the costs out
    is what stops one being smuggled into a decision that should not
    depend on them.

    ``mode`` and ``placement`` are ``None`` for an ad set built by hand in
    the provider's console. That is "unknown", not "interests": a mode is
    never read off the spec, because a broad spec somebody chose and a
    spec whose interests all failed look identical - so an ad set with no
    stored choice has no mode to report.
    """

    external_id: str
    stage: LifecycleStage
    delivery: str = ""
    counts_leads: bool = False
    # Ads actually delivering under this ad set. One means nothing is
    # being compared; two or three mean the creative test is running.
    creatives: int = 0
    mode: TargetingMode | None = None
    placement: PlacementMode | None = None


@dataclass(frozen=True, slots=True)
class StrategyState:
    """One account, assembled for the playbook.

    Carries :class:`SignalHistory` rather than a pre-computed maturity:
    the playbook derives maturity itself, once, from the same thresholds
    every strategy then sees. A caller that shipped a maturity of its own
    could disagree with the history beside it, and nothing downstream
    could tell which one to believe.
    """

    history: SignalHistory
    assets: AudienceAssets
    adsets: tuple[AdSetPosture, ...] = ()
    # Campaigns actually delivering. Zero is the loudest state an account
    # has: nothing else in the playbook matters until something runs.
    active_campaigns: int = 0


__all__ = ["AdSetPosture", "AudienceAssets", "StrategyState"]
