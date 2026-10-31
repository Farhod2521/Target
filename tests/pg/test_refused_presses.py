"""A refused press answers the same way from every module, and costs one question."""

from pathlib import Path
from typing import Any

import pytest
from adskit.errors import (
    InvalidRequest,
    PaymentMethodMissing,
    ProviderError,
    RateLimited,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import LibraryUpload
from app.modules.ads.models import CampaignLaunch, LaunchCreative
from app.modules.ads.selectors.cards import variant_card
from app.modules.ads.services import library
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.chat.constants import REFUSAL_OPERATION_LABELS
from app.modules.chat.models import RefusalAnswer
from app.modules.chat.services.explain import explain_action
from app.modules.chat.services.refused import OPERATIONS, TITLES
from app.modules.integrations import services as integrations
from app.modules.integrations.services import connect
from tests.pg.test_refusal_answers import _Claude, _claude, _owner

KEY = "audience:meta:100/2654"
URL = "/api/v1/connections/audiences"
ANSWER_URL = "/api/v1/refusals/answer"


def _refusal(key: str = "meta:100/2654") -> ProviderError:
    error = InvalidRequest(
        "Invalid parameter | code 100/2654",
        code="100",
        user_title="Auditoriya yaratilmadi",
        user_message="Shartlarni qabul qiling.",
    )
    error.key = key
    return error


def _headers(owner: User) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + tokens.issue(subject=str(owner.id), kind="access", now=utcnow())
    }


def _refusing(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def create_audience(*_: Any, **__: Any) -> None:
        raise error

    monkeypatch.setattr(integrations, "create_audience", create_audience)


def _press(client: TestClient, owner: User) -> Any:
    return client.post(URL, json={"name": "A"}, headers=_headers(owner))


def _explaining(queued: list) -> list[tuple[Any, ...]]:
    return [args for name, args in queued if name.endswith("explain_action_refusal")]


def test_a_new_refusal_answers_the_dialog_and_asks_claude_once(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _account = _owner(db)
    _refusing(monkeypatch, _refusal())

    first = _press(client, owner)
    _press(client, owner)

    body = first.json()
    assert first.status_code == 422
    assert body["code"] == "provider_refused"
    assert body["refusal"]["key"] == KEY
    assert body["refusal"]["explaining"] is True and body["refusal"]["html"] is None
    assert body["refusal"]["providerWords"] == (
        "Auditoriya yaratilmadi — Shartlarni qabul qiling."
    )
    assert body["refusal"]["title"] == "Meta auditoriyani qabul qilmadi"
    assert len(_explaining(queued)) == 1


def test_the_written_answer_reaches_the_dialog_with_the_owners_links(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _account = _owner(db)
    _refusing(monkeypatch, _refusal())
    waiting = _press(client, owner).json()["refusal"]
    payload, language = _explaining(queued)[0]
    monkeypatch.setattr("app.modules.chat.services.explain.claude", _claude)

    explain_action(db, payload=payload, language=language)
    db.commit()
    answer = client.get(
        ANSWER_URL, params={"key": waiting["key"]}, headers=_headers(owner)
    ).json()
    again = _press(client, owner).json()["refusal"]

    assert _Claude.asked == 1
    kept = db.scalar(select(RefusalAnswer).where(RefusalAnswer.key == KEY))
    assert kept is not None and kept.prompt_version.startswith("action-")
    assert answer["explaining"] is False
    assert "Ads Manager" in answer["html"] and "[[" not in answer["html"]
    assert again["html"] == answer["html"] and again["explaining"] is False


def test_a_passing_fault_is_told_to_wait_and_costs_no_question(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _account = _owner(db)
    _refusing(monkeypatch, RateLimited("limit", retry_after_seconds=120))

    refusal = _press(client, owner).json()["refusal"]

    assert refusal["retryable"] is True and refusal["key"] is None
    assert refusal["retryAfterSeconds"] == 120
    assert _explaining(queued) == []


def test_a_refusal_with_a_written_sentence_costs_no_question(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner(db)
    _refusing(monkeypatch, PaymentMethodMissing("no card", code="1359188"))

    refusal = _press(client, owner).json()["refusal"]

    assert refusal["fix"]["label"] == "To'lov sahifasini ochish"
    assert account.external_id.removeprefix("act_") in refusal["fix"]["url"]
    assert refusal["key"] is None and _explaining(queued) == []


def test_a_refusal_with_no_name_still_says_where_to_look(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _account = _owner(db)
    _refusing(monkeypatch, InvalidRequest("nothing"))

    refusal = _press(client, owner).json()["refusal"]

    assert refusal["cause"] == "Meta aniq sababini aytmadi."
    assert refusal["steps"]
    assert _explaining(queued) == []


def test_a_connection_refused_for_good_goes_back_with_its_key(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _account = _owner(db)

    class Connect:
        def complete(self, **_: Any) -> None:
            raise _refusal()

    class Registered:
        connect = Connect()

    monkeypatch.setattr(connect.registry, "get", lambda _provider: Registered())
    monkeypatch.setattr(
        "app.modules.billing.selectors.may_prepare", lambda *_, **__: True
    )

    with pytest.raises(Exception) as caught:
        connect.complete_connection(db, user=owner, code="c", redirect_uri="u")

    assert caught.value.refusal["key"] == "connect:meta:100/2654"


def test_a_refused_file_keeps_why_for_the_screen_that_reads_it_later(
    db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner(db)
    launch = CampaignLaunch(
        owner_id=owner.id, ad_account_id=account.id, provider="meta", status="ready"
    )
    db.add(launch)
    db.flush()
    row = LaunchCreative(
        owner_id=owner.id,
        launch_id=launch.id,
        media_upload="launch/file.jpg",
        library_upload=str(LibraryUpload.PENDING),
    )
    log = ActionLog(
        owner_id=owner.id,
        action=str(ActionType.MEDIA_UPLOAD),
        status=str(ActionStatus.PENDING),
    )
    db.add_all([row, log])
    db.commit()
    monkeypatch.setattr(
        library, "launch_account_and_token", lambda *_, **__: (account, "t")
    )

    def send(*_: Any, **__: Any) -> None:
        raise _refusal()

    monkeypatch.setattr(library, "_send", send)

    assert library.upload_to_library(db, creative_id=row.id, log_id=log.id) == "failed"

    db.expire_all()
    assert row.library_upload == LibraryUpload.FAILED
    assert row.upload_refusal["key"] == "media:meta:100/2654"
    assert row.upload_refusal["explaining"] is True
    assert variant_card(row, now=utcnow())["upload_refusal"] == row.upload_refusal
    assert len(_explaining(queued)) == 1


def test_every_operation_is_named_for_the_office_and_used_somewhere() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("app").rglob("*.py")
    )

    assert set(OPERATIONS) == set(TITLES)
    assert set(OPERATIONS) <= set(REFUSAL_OPERATION_LABELS)
    for operation in OPERATIONS:
        assert f'operation="{operation}"' in source
