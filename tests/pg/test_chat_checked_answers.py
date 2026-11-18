"""The office's written answers for Meta's errors reach the assistant only
once a person has checked them (owner's decision, 2026-11-18). Until then
the help base's own steps are given, as before."""

from datetime import timedelta

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.models import Ad, CampaignLaunch
from app.modules.ads.selectors.rejections import review_key
from app.modules.chat.models import RefusalAnswer
from app.modules.chat.selectors.lookups import answer_lookup
from app.modules.chat.selectors.refusal import key_for
from app.modules.chat.selectors.scope import asked_scopes
from core.chat import lookup_arguments as args
from tests.pg.conftest import sign_up
from tests.pg.test_chat import _account, _mirror

WORDS = "Matnda tana haqida gap bor. 1. Matnni o'zgartiring. 2. [[ads_manager]] da saqlang."


def _read(db: Session, owner, name: str, value) -> str:  # type: ignore[no-untyped-def]
    scope, counted = asked_scopes(db, owner=owner)
    return answer_lookup(
        db,
        owner=owner,
        name=name,
        arguments=value,
        scope=scope,
        now=utcnow(),
        counted=counted,
    )


def _refused_ad(client: TestClient, db: Session):  # type: ignore[no-untyped-def]
    sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)
    ad = db.scalar(select(Ad).where(Ad.owner_id == owner.id))
    assert ad is not None
    ad.delivery = "rejected"
    ad.review_feedback = {"overall": {"Spam": "The ad looks like spam."}}
    db.commit()
    return owner, ad


def _answer(db: Session, key: str, *, checked: bool) -> None:
    db.add(
        RefusalAnswer(
            key=key,
            answer_uz=WORDS,
            prompt_version="v1",
            edited_at=utcnow() - timedelta(hours=1) if checked else None,
        )
    )
    db.commit()


def test_an_unchecked_answer_is_not_given(client: TestClient, db: Session) -> None:
    owner, ad = _refused_ad(client, db)
    _answer(db, review_key(ad), checked=False)
    text = _read(db, owner, "ad_details", args.AdLookup(ad_id=ad.external_id))
    assert "checked by Support" not in text
    assert "Matnda tana haqida" not in text
    assert "## Ready fix:" in text


def test_a_checked_answer_replaces_the_general_steps(
    client: TestClient, db: Session
) -> None:
    owner, ad = _refused_ad(client, db)
    _answer(db, review_key(ad), checked=True)
    text = _read(db, owner, "ad_details", args.AdLookup(ad_id=ad.external_id))
    assert "## Ready fix, checked by Support for exactly this error" in text
    assert "Matnda tana haqida gap bor." in text
    # The link is spelled out for a chat: its label and its address.
    assert "Ads Manager'ni ochish (https://" in text
    assert "## Ready fix: Meta reklamani rad etdi" not in text


def test_a_refused_launch_gives_its_checked_answer(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    owner, account, page = _account(db)
    launch = CampaignLaunch(
        owner_id=owner.id,
        ad_account_id=account.id,
        page_id=page.id,
        provider=PROVIDER,
        status="failed",
        error_code="provider",
        error_message="No payment method - code 100/1359188",
    )
    db.add(launch)
    db.commit()
    _answer(db, key_for(launch), checked=True)
    text = _read(db, owner, "preparations", args.Window())
    assert "checked by Support for exactly this error" in text
    assert "Matnda tana haqida gap bor." in text
