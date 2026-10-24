"""adskit values: frozen, and typed enough that a wrong id cannot be passed.

No database, no Django, no network.
"""

import dataclasses
from datetime import date

import pytest
from adskit import ActionResult, ExternalRef, MetricsDTO, MinorUnits
from pydantic import ValidationError

REF = ExternalRef(provider="meta", level="adset", id="120210000000000")


def test_ref_renders_for_logs_and_idempotency_keys() -> None:
    assert str(REF) == "meta:adset:120210000000000"


def test_ref_is_hashable_and_compares_by_value() -> None:
    """Refs are used as dict keys while reconciling a sync."""
    same = ExternalRef(provider="meta", level="adset", id="120210000000000")

    assert same == REF
    assert len({REF, same}) == 1


def test_ref_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        REF.id = "999"  # type: ignore[misc]


def test_parsed_dto_is_frozen() -> None:
    """A DTO edited on the far side of a boundary is a bug that reads fine."""
    metrics = MetricsDTO(
        ref=REF,
        day=date(2026, 8, 15),
        spend_minor=MinorUnits(50_000_00),
        currency="UZS",
        impressions=1200,
    )

    with pytest.raises(ValidationError):
        metrics.impressions = 0


def test_unknown_field_is_rejected_rather_than_ignored() -> None:
    """A provider response that grew a field should fail here, not silently.

    extra="forbid" is what turns a Meta schema change into a readable error
    at the adapter instead of a missing number on a dashboard.
    """
    with pytest.raises(ValidationError):
        MetricsDTO(ref=REF, day=date(2026, 8, 15), cost_per_lead=42)


def test_action_result_defaults_to_dry_run() -> None:
    """Writing to a live ad account is opt-in, never the default."""
    assert ActionResult(ok=True, ref=REF).dry_run is True


def test_action_result_records_what_the_provider_dropped() -> None:
    """Meta removes some placements silently and still answers 200."""
    result = ActionResult(
        ok=True,
        ref=REF,
        applied={"publisher_platforms": ["facebook", "instagram"]},
        dropped={"messenger_positions": ["story"]},
        dry_run=False,
    )

    assert result.dropped == {"messenger_positions": ["story"]}
