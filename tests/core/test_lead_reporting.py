"""Which verdicts go back to the provider, and when.

No Django and no database, which is why the rules were put in ``core``: the
awkward half of this feature is two windows pointing in opposite directions,
and every case below is three datetimes and an integer.

The settle window is the one worth reading twice. It exists because no
platform lets a server event be withdrawn - so a verdict sent the instant a
button is pressed has already taught an optimiser something a correction
forty seconds later cannot take back.
"""

from datetime import UTC, datetime, timedelta

from core.leads import Verdict, due, event_key, expired, is_reportable, is_settled

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
WINDOW = 7
SETTLE = 30


def a_verdict(
    *,
    minutes_ago: int = 60,
    status: str = "qualified",
    lead: str = "L1",
    **extra: object,
) -> Verdict:
    return Verdict(
        lead_external_id=lead,
        status=status,
        decided_at=NOW - timedelta(minutes=minutes_ago),
        **extra,  # type: ignore[arg-type]
    )


# --- The settle window ----------------------------------------------------
def test_a_verdict_pressed_a_moment_ago_is_not_sent() -> None:
    """The whole reason this is a sweep and not a button. A misclick is
    noticed while somebody is still looking at the screen, and a platform
    cannot un-learn what it has already been told."""
    assert due(verdicts=[a_verdict(minutes_ago=1)], now=NOW, window_days=WINDOW) == ()


def test_a_verdict_that_has_stood_is_sent() -> None:
    ready = due(
        verdicts=[a_verdict(minutes_ago=SETTLE + 1)], now=NOW, window_days=WINDOW
    )

    assert len(ready) == 1
    assert ready[0][1] == "qualified"


def test_the_boundary_counts_as_settled() -> None:
    """Exactly at the window, not merely past it. The sweep runs on a
    schedule, and a strict comparison would leave a verdict decided on a
    boundary waiting a whole extra cycle for no reason anybody could see."""
    assert is_settled(
        decided_at=NOW - timedelta(minutes=SETTLE), now=NOW, minutes=SETTLE
    )


# --- The provider's window ------------------------------------------------
def test_a_verdict_older_than_the_window_is_never_sent() -> None:
    """The provider answers 200 and does not count it. Going on retrying is
    a sweep that grows a tail it can never clear."""
    old = a_verdict(minutes_ago=60 * 24 * (WINDOW + 1))

    assert due(verdicts=[old], now=NOW, window_days=WINDOW) == ()
    assert expired(verdicts=[old], now=NOW, window_days=WINDOW) == (old,)


def test_a_verdict_still_settling_is_not_reported_as_expired() -> None:
    """ "Not yet" and "never" are different answers and the caller does
    different things with them - one is posted later, the other is marked so
    the sweep stops carrying it. Confusing them would stamp a verdict as
    finished with thirty minutes still to run."""
    fresh = a_verdict(minutes_ago=1)

    assert due(verdicts=[fresh], now=NOW, window_days=WINDOW) == ()
    assert expired(verdicts=[fresh], now=NOW, window_days=WINDOW) == ()


def test_the_window_is_measured_on_the_verdict_not_the_lead() -> None:
    """A lead submitted in May and judged this morning is fresh news. It is
    the judgement the provider has never heard, and dating the event from
    the submission would age out the one fact worth sending."""
    assert is_reportable(
        decided_at=NOW - timedelta(minutes=5), now=NOW, window_days=WINDOW
    )


# --- The vocabulary -------------------------------------------------------
def test_a_status_nobody_mapped_is_silence() -> None:
    """The column is wider than the two values a person can choose - a CRM
    writing its own funnel words is the next source of these rows - and an
    event sent under a guessed name is counted by nothing and cannot be
    withdrawn."""
    assert due(verdicts=[a_verdict(status="warm")], now=NOW, window_days=WINDOW) == ()


def test_both_verdicts_a_person_can_give_are_sent() -> None:
    """The negative one as much as the positive. An optimiser told only
    about the good leads learns what a good lead looks like against no
    contrast at all."""
    ready = due(
        verdicts=[
            a_verdict(status="qualified", lead="A"),
            a_verdict(status="unqualified", lead="B"),
        ],
        now=NOW,
        window_days=WINDOW,
    )

    assert [stage for _verdict, stage in ready] == ["qualified", "unqualified"]


# --- The idempotency key --------------------------------------------------
def test_the_same_verdict_sends_the_same_key() -> None:
    """The sweep retries anything unacknowledged, so a worker restarted
    mid-flight resends - and the provider has to count that once."""
    first = event_key(provider="meta", lead_external_id="9", stage="qualified")
    again = event_key(provider="meta", lead_external_id="9", stage="qualified")

    assert first == again


def test_a_changed_mind_sends_a_different_key() -> None:
    """It is a genuinely different event and must not be de-duplicated away
    against the one it replaces. What it cannot do is retract that one -
    which is what the settle window above exists for."""
    before = event_key(provider="meta", lead_external_id="9", stage="qualified")
    after = event_key(provider="meta", lead_external_id="9", stage="unqualified")

    assert before != after


def test_two_providers_never_share_a_key() -> None:
    """A lead id is a bare number on every platform. Without the provider in
    the key, one platform's de-duplication could swallow another's event."""
    assert event_key(
        provider="meta", lead_external_id="9", stage="qualified"
    ) != event_key(provider="google", lead_external_id="9", stage="qualified")
