"""TZ 3: a website event's result, counted from Meta's results and named."""

import pytest

from app.modules.chat.selectors.day_lines import report_kind, result_count
from app.modules.metrics.selectors.results import counted_result, uncounted_note
from app.modules.notifications.services.compose_day_pair import _site_event_name


@pytest.mark.parametrize(
    ("event", "word"),
    [
        ("COMPLETE_REGISTRATION", "ro'yxatdan o'tish"),
        ("PURCHASE", "xarid"),
        ("CONTACT", "bog'lanish"),
        ("OTHER", "natija"),
    ],
)
def test_a_site_event_is_counted_from_results_under_its_name(
    event: str, word: str
) -> None:
    promoted = {"pixel_id": "1", "custom_event_type": event}

    assert counted_result("OFFSITE_CONVERSIONS", promoted) == ("results", word)
    assert uncounted_note("OFFSITE_CONVERSIONS", promoted) == ""


def test_the_pixels_lead_stays_on_the_lead_count() -> None:
    promoted = {"pixel_id": "1", "custom_event_type": "LEAD"}

    assert counted_result("OFFSITE_CONVERSIONS", promoted) == (
        "leads_reported",
        "murojaat",
    )


def test_a_custom_conversion_is_counted_from_results() -> None:
    promoted = {"custom_event_type": "LEAD", "custom_conversion_id": "9"}

    assert counted_result("OFFSITE_CONVERSIONS", promoted) == ("results", "murojaat")


def test_the_bot_names_each_site_event() -> None:
    kind = report_kind(
        "none",
        goal="OFFSITE_CONVERSIONS",
        promoted={"custom_event_type": "PURCHASE"},
    )

    assert kind == "site_event:PURCHASE"
    assert _site_event_name(kind) == "Xarid"
    assert result_count(kind=kind, sums={"results": 4}, ours=0) == 4
