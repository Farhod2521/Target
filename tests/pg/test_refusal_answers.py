"""A refused launch or change is explained where it failed, with no chat.

A refusal the screen has a sentence for keeps its sentence. One it has none
for is sent to Claude once per Meta code and language; the answer is kept and
every later owner with the same refusal reads it at once.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from adskit.errors import NotFound, ProviderError
from fastapi.testclient import TestClient
from llmkit import LLMResult
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.actions import executor
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.services import manage
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from app.modules.chat.constants import REFUSAL_LOCK
from app.modules.chat.models import RefusalAnswer
from app.modules.chat.services.explain import explain_change, explain_launch
from tests.pg.test_ads_manage import _mirror
from tests.pg.test_ads_writes import RefusingCampaigns, _log, _refusing, _signed_in
from tests.pg.test_cabinet_flows import _cabinet

TOO_LOW = ProviderError(
    "Invalid parameter | Campaign Spending Limit Too Low | code 100/1885272",
    code="100",
    user_title="Campaign Spending Limit Too Low",
)
KEY = "change:meta:100/1885272"
LAUNCH_KEY = "meta:100/1487851"
ANSWER = (
    "Kampaniya uchun belgilangan chegara Meta ruxsat bergandan past.\n\n"
    "1. Ads Manager'da kampaniyani oching [[ads_manager]]\n"
    "2. Chegarani oshiring\n\n"
    "Keyin o'zgarishni qayta yuboring."
)


@dataclass
class _Stream:
    pieces: list[str]
    result: Any = None

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield from self.pieces


class _Claude:
    asked = 0
    answer = ANSWER

    def stream(self, **asked: Any) -> _Stream:
        _Claude.asked += 1
        text = _Claude.answer
        return _Stream(
            pieces=[text[:20], text[20:]],
            result=LLMResult(
                value=text,
                input_tokens=10,
                output_tokens=5,
                cost_micros=1,
                currency="USD",
                latency_ms=1,
                prompt_name=asked.get("prompt_name", ""),
                prompt_version=asked.get("prompt_version", ""),
                model="test",
            ),
        )


@contextmanager
def _claude(**_: Any):  # type: ignore[no-untyped-def]
    yield _Claude()


@pytest.fixture(autouse=True)
def _unlocked() -> None:
    for key in (KEY, LAUNCH_KEY):
        for language in ("uz", "ru", "en"):
            cache.delete(REFUSAL_LOCK.format(key=key, language=language))
    _Claude.asked = 0
    _Claude.answer = ANSWER


def _owner(db: Session) -> tuple[User, Any]:
    owner = User(
        email="refused@example.com", full_name="R", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.commit()
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    _mirror(db, owner, account.id)
    return owner, account


def _refused(
    db: Session, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> tuple[User, str]:
    owner, account = _owner(db)
    _refusing(monkeypatch, executor, RefusingCampaigns(error))
    _signed_in(monkeypatch, executor, account)
    log_id = _log(db, owner, ActionType.PAUSE, ManagedLevel.ADSET, "s_1")
    assert manage.apply_change(db, log_id=log_id) == "failed"
    return owner, log_id


def _explaining(queued: list) -> list[tuple[Any, ...]]:
    return [args for name, args in queued if name.endswith("explain_change_refusal")]


def test_a_refusal_without_a_sentence_is_sent_to_be_explained(
    db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, log_id = _refused(db, monkeypatch, TOO_LOW)

    assert _explaining(queued) == [(log_id, owner.language)]


def test_a_refusal_the_screen_has_words_for_is_not(
    db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refused(db, monkeypatch, NotFound("gone | code 100/33", code="100"))

    assert _explaining(queued) == []


def test_the_answer_is_written_once_and_kept_for_everyone(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner_row, log_id = _refused(db, monkeypatch, TOO_LOW)
    monkeypatch.setattr("app.modules.chat.services.explain.claude", _claude)

    first = explain_change(db, log_id=log_id, language="uz")
    db.commit()
    again = explain_change(db, log_id=log_id, language="uz")

    assert first == again == ANSWER
    assert _Claude.asked == 1
    kept = db.scalar(select(RefusalAnswer).where(RefusalAnswer.key == KEY))
    assert kept is not None
    assert kept.answer_uz == ANSWER
    assert kept.prompt_version.startswith("change-")
    assert kept.provider_title == "Campaign Spending Limit Too Low"


def test_the_screen_shows_the_answer_where_the_change_failed(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, log_id = _refused(db, monkeypatch, TOO_LOW)
    headers = {
        "Authorization": "Bearer "
        + tokens.issue(subject=str(owner.id), kind="access", now=utcnow())
    }
    path = "/api/v1/campaigns/manage/adset/s_1/state"

    waiting = client.get(path, headers=headers).json()["failure"]
    language = _explaining(queued)[-1][1]
    monkeypatch.setattr("app.modules.chat.services.explain.claude", _claude)
    explain_change(db, log_id=log_id, language=language)
    db.commit()
    shown = client.get(path, headers=headers).json()["failure"]

    assert waiting["explaining"] is True and not waiting["explanationHtml"]
    assert not shown["explaining"]
    assert "Ads Manager&#x27;ni ochish" in shown["explanationHtml"] or (
        "Ads Manager'ni ochish" in shown["explanationHtml"]
    )
    assert "[[" not in shown["explanationHtml"]
    assert db.get(ActionLog, log_id).error_code == "refused"


# --- A refused launch ----------------------------------------------------------


def _refused_launch(db: Session) -> tuple[User, CampaignLaunch]:
    from app.modules.ads.services import creation

    owner, account = _owner(db)
    launch = CampaignLaunch(
        owner_id=owner.id,
        ad_account_id=account.id,
        page_id=_page_of(db, owner),
        provider="meta",
        status="creating",
    )
    db.add(launch)
    db.commit()
    creation._fail(
        db,
        launch,
        code="refused",
        message="Invalid parameter | Location not recognized | code 100/1487851",
        detail={"title": "Location not recognized", "message": "Pick another place"},
    )
    return owner, launch


def _page_of(db: Session, owner: User) -> Any:
    from app.modules.integrations.models import PageAccount

    return db.scalar(select(PageAccount.id).where(PageAccount.owner_id == owner.id))


def test_a_refused_launch_is_sent_to_be_explained_without_a_chat(
    db: Session, queued: list
) -> None:
    owner, launch = _refused_launch(db)

    sent = [args for name, args in queued if name.endswith("explain_launch_refusal")]
    assert sent == [(str(launch.id), owner.language)]


def test_the_review_shows_the_launch_answer_and_polls_until_it_comes(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, launch = _refused_launch(db)
    headers = {
        "Authorization": "Bearer "
        + tokens.issue(subject=str(owner.id), kind="access", now=utcnow())
    }
    path = f"/api/v1/launch/{launch.id}/review/state"

    waiting = client.get(path, headers=headers).json()["state"]
    monkeypatch.setattr("app.modules.chat.services.explain.claude", _claude)
    for language in ("uz", "ru", "en"):
        explain_launch(db, launch_id=str(launch.id), language=language)
    db.commit()
    shown = client.get(path, headers=headers).json()["state"]

    assert waiting["explaining"] is True and waiting["keep_polling"] is True
    assert shown["explaining"] is False and "[[" not in shown["explanation_html"]
    assert "Ads Manager" in shown["explanation_html"]


def test_an_answer_that_cannot_be_shared_stops_the_wait(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, launch = _refused_launch(db)
    monkeypatch.setattr("app.modules.chat.services.explain.claude", _claude)
    _Claude.answer = "Byudjetingiz 37 000 so'm - juda kam."
    for language in ("uz", "ru", "en"):
        assert explain_launch(db, launch_id=str(launch.id), language=language) == ""
    db.commit()
    headers = {
        "Authorization": "Bearer "
        + tokens.issue(subject=str(owner.id), kind="access", now=utcnow())
    }

    state = client.get(f"/api/v1/launch/{launch.id}/review/state", headers=headers)

    assert state.json()["state"]["explaining"] is False
    assert (
        db.scalar(select(RefusalAnswer).where(RefusalAnswer.key == LAUNCH_KEY)) is None
    )
