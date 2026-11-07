"""core/targeting/buttons.py: which word a running advert's button may take (TZ 2.3)."""

import pytest

from core.targeting.buttons import kept_destination


@pytest.mark.parametrize(
    ("current", "kind"),
    [
        ({"type": "SIGN_UP", "value": {"lead_gen_form_id": "f", "link": "x"}}, "form"),
        ({"type": "LEARN_MORE", "value": {"link": "https://a.uz"}}, "website"),
        ({"type": "INSTAGRAM_MESSAGE", "value": {"app_destination": "x"}}, None),
        ({"type": "CALL_NOW", "value": {"link": "tel:1"}}, None),
        ({"type": "VIEW_INSTAGRAM_PROFILE", "value": {"link": "x"}}, None),
        ({}, None),
    ],
)
def test_the_button_keeps_where_it_leads(current: dict, kind: str | None) -> None:
    assert kept_destination(current=current) == kind
