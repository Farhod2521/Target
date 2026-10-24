"""core/agent/contracts.py: domain values are values. No database here."""

import dataclasses

import pytest
from adskit import ExternalRef

from core.agent.contracts import Finding, GuardrailVerdict, Policy


def _finding() -> Finding:
    return Finding(
        kind="pause",
        rule="wasting",
        ref=ExternalRef(provider="meta", level="adset", id="123"),
        weight=450_000,
        evidence={"days": 5, "spend_minor": 450_000, "leads": 0},
    )


def test_finding_is_immutable() -> None:
    """A finding edited after the guardrail saw it is a bug that hides."""
    finding = _finding()

    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.kind = "resume"  # type: ignore[misc]


def test_verdict_uses_slots() -> None:
    """Slots keep per-ad-set allocations cheap: no per-instance __dict__."""
    verdict = GuardrailVerdict(allowed=False, reason="Adset o'rganish bosqichida")

    assert not hasattr(verdict, "__dict__")
    assert GuardrailVerdict.__slots__ == ("allowed", "reason")


def test_finding_carries_a_typed_target() -> None:
    """A bare id could not say which provider or level it belonged to."""
    finding = _finding()

    assert str(finding.ref) == "meta:adset:123"
    assert finding.level == "adset"


def test_finding_keeps_the_numbers_it_was_made_from() -> None:
    """The evidence is the whole reason a late answer can be re-checked.

    Recomputed a fortnight later the same window returns different figures,
    and a screen showing those beside a sentence written about the old ones
    is an explanation that contradicts itself.
    """
    finding = _finding()

    assert finding.evidence["spend_minor"] == 450_000
    assert finding.evidence["leads"] == 0


def test_a_policy_nobody_configured_is_still_a_policy() -> None:
    """Every threshold has a default, so an untouched account behaves.

    The settings screen exposes five of these; the rest are media buying
    rather than preferences, and asking a shop owner what counts as a
    starved ad set is asking a question they have no way to answer.
    """
    policy = Policy()

    assert policy.window_days == 7
    assert policy.max_per_run == 3
    assert policy.win_share_pct < 100 < policy.lose_share_pct
