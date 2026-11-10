"""The login that cannot reach an ad account arrives as its own class.

Both bodies are the ones production received on 2026-11-09 for an account the
owner had chosen with one Facebook profile and then reconnected with another.
"""

from typing import Any

import httpx
import pytest
from adskit.errors import (
    AdAccountUnreachable,
    InvalidRequest,
    PermissionDenied,
)
from metaads.adapter import translate_error
from metaads.client import GraphClient

POST_REFUSED = (
    "Unsupported post request. Object with ID 'act_1001166539663370' does not "
    "exist, cannot be loaded due to missing permissions, or does not support "
    "this operation. Please read the Graph API documentation at "
    "https://developers.facebook.com/docs/graph-api"
)
READ_REFUSED = (
    "(#200) Ad account owner has NOT grant ads_management or ads_read "
    "permission, refer to https://developers.facebook.com/docs/marketing-api/"
    "get-started/authorization/#permissions-and-features for details."
)


def _translated(status: int, **error: Any) -> Exception:
    raised = GraphClient._translate(httpx.Response(status, json={"error": error}))
    return translate_error(raised)


def test_the_refused_write_on_the_account_is_unreachable() -> None:
    found = _translated(400, message=POST_REFUSED, code=100, error_subcode=33)

    assert type(found) is AdAccountUnreachable
    assert found.key == "meta:100/33"


def test_the_refused_read_naming_the_owner_is_unreachable() -> None:
    found = _translated(400, message=READ_REFUSED, code=200)

    assert type(found) is AdAccountUnreachable


def test_it_is_still_a_permission_refusal() -> None:
    """Every caller that only needs to stop, and never take the login down."""
    found = _translated(400, message=READ_REFUSED, code=200)

    assert isinstance(found, PermissionDenied)


@pytest.mark.parametrize(
    "message",
    [
        "Unsupported post request. Object with ID '120215' does not exist, "
        "cannot be loaded due to missing permissions",
        "Unsupported get request. Object with ID '987654321' does not exist",
    ],
)
def test_100_33_about_any_other_object_stays_what_it_was(message: str) -> None:
    found = _translated(400, message=message, code=100, error_subcode=33)

    assert type(found) is InvalidRequest


def test_a_plain_200_stays_a_permission_refusal() -> None:
    found = _translated(400, message="(#200) Permissions error", code=200)

    assert type(found) is PermissionDenied
