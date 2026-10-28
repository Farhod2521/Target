"""Every refusal says which one it is, so a client can branch on it."""

import asyncio
import json

from app.common.exceptions import DomainError, InputRefused, NotFound
from app.main import app
from app.modules.ads.exceptions import FreeProposalsUsed, NoAdAccount, ProfileIncomplete
from app.modules.ads.inputs.destination import web_address
from app.modules.billing.exceptions import (
    NoEntitlement,
    PlanSizeReached,
    SubscriptionExpired,
    TrialLimitReached,
)


def test_a_refusal_is_named_after_its_class() -> None:
    assert [
        cls.code
        for cls in (
            NoEntitlement,
            SubscriptionExpired,
            TrialLimitReached,
            PlanSizeReached,
            FreeProposalsUsed,
            ProfileIncomplete,
            NoAdAccount,
        )
    ] == [
        "no_entitlement",
        "subscription_expired",
        "trial_limit_reached",
        "plan_size_reached",
        "free_proposals_used",
        "profile_incomplete",
        "no_ad_account",
    ]


def test_a_family_named_by_hand_keeps_its_code() -> None:
    class Unreadable(InputRefused):
        pass

    class Gone(NotFound):
        pass

    assert (Unreadable.code, Gone.code) == ("invalid_input", "not_found")
    assert DomainError("x").code == "domain_error"


def test_acronyms_read_as_one_word() -> None:
    class CRMSeatTaken(DomainError):
        pass

    assert CRMSeatTaken.code == "crm_seat_taken"


def test_the_answer_carries_the_code_and_the_hints() -> None:
    handler = app.exception_handlers[DomainError]
    refused = InputRefused(
        {"link_url": "Sayt kerak."}, hints={"offer_outcome": "profile"}
    )

    answer = asyncio.run(handler(None, refused))  # type: ignore[arg-type]

    assert answer.status_code == 422
    assert json.loads(answer.body) == {
        "detail": "Sayt kerak.",
        "code": "invalid_input",
        "problems": {"link_url": "Sayt kerak."},
        "hints": {"offer_outcome": "profile"},
    }


def test_a_site_address_may_be_cyrillic_but_not_malformed() -> None:
    assert web_address("бахор.уз") == "https://бахор.уз"
    assert web_address("www.my-cafe.co.uk") == "https://www.my-cafe.co.uk"
    assert [web_address(raw) for raw in ("-bad-.uz", "a_b.uz", "localhost")] == [
        "",
        "",
        "",
    ]
