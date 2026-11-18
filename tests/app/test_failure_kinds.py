"""Whose a failure is: Support's (Meta's), nobody's (passing), or ours."""

import pytest

from app.modules.ads.failure_kinds import (
    PASSING_CODES,
    SYSTEM_CODES,
    FailureKind,
    kind_of,
)
from app.modules.ads.services.creation import FAILURE_CODES
from app.modules.ads.services.manage import PROVIDER_FAILURES


def test_no_code_is_both_passing_and_ours() -> None:
    assert not PASSING_CODES & SYSTEM_CODES


@pytest.mark.parametrize(
    "code",
    sorted(
        (set(FAILURE_CODES.values()) | set(PROVIDER_FAILURES.values())) - PASSING_CODES
    ),
)
def test_every_word_a_provider_refusal_is_turned_into_is_metas(code: str) -> None:
    assert kind_of(code) == FailureKind.META


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("refused", FailureKind.META),
        ("payment_missing", FailureKind.META),
        ("account_action", FailureKind.META),
        ("190", FailureKind.META),
        ("", FailureKind.META),
        (None, FailureKind.META),
        ("temporary", FailureKind.PASSING),
        ("613", FailureKind.PASSING),
        ("learning", FailureKind.PASSING),
        ("site_missing", FailureKind.PASSING),
        ("unknown", FailureKind.SYSTEM),
        ("schema_error", FailureKind.SYSTEM),
        ("stalled", FailureKind.SYSTEM),
        ("not_applied", FailureKind.SYSTEM),
    ],
)
def test_kind_of(code: str | None, kind: FailureKind) -> None:
    assert kind_of(code) == kind
