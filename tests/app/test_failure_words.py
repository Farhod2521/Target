"""A failed change is explained to the owner in their words, not the log's."""

from app.common.db import utcnow
from app.modules.ads.routers import _action
from app.modules.ads.selectors.failures import FALLBACK, SENTENCES
from app.modules.audit.constants import ActionStatus
from app.modules.audit.models import ActionLog


def _failed(code: str, message: str, said: dict[str, str] | None = None) -> ActionLog:
    return ActionLog(
        action="targeting_swap",
        status=str(ActionStatus.FAILED),
        error_code=code,
        error_message=message,
        result_payload=said or {},
        dry_run=False,
        created_at=utcnow(),
        dropped={},
    )


def test_a_refusal_is_answered_in_the_owners_sentence() -> None:
    row = _action(_failed("changed_elsewhere", "the audience is not the one edited"))

    assert row["error_message"] == SENTENCES["changed_elsewhere"][0]


def test_what_meta_wrote_for_the_advertiser_follows_the_sentence() -> None:
    row = _action(
        _failed(
            "refused",
            "[100/1487] Invalid parameter",
            {"user_title": "Byudjet juda kam", "user_message": "Kamida 1$ kiriting."},
        )
    )

    assert row["error_message"] == (
        f"{FALLBACK[0]} Byudjet juda kam Kamida 1$ kiriting."
    )
    assert "Invalid parameter" not in row["error_message"]
