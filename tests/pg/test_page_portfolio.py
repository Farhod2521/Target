"""A new page + ad account pair only from the page's own business portfolio.

Against PostgreSQL: the rule on every new pair, pairs made before it left
alone, the picker's answer, and a new ad account made in the portfolio.
"""

from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from metaads import PROVIDER
from metaads.dto import PageDTO
from metaads.errors import MetaAPIError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import encrypt, fingerprint
from app.modules.accounts.models import User
from app.modules.integrations.exceptions import (
    AccountNotForPage,
    AdAccountLimit,
    AdAccountNoPortfolio,
)
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PagePair,
    ProviderConnection,
)
from app.modules.integrations.selectors import page_fits, page_pairs
from app.modules.integrations.services import cabinet, sync
from tests.pg.conftest import sign_up


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())


def _user(client: TestClient, db: Session) -> tuple[User, dict[str, str]]:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    return user, auth


def _connection(db: Session, user: User) -> ProviderConnection:
    connection = ProviderConnection(
        owner_id=user.id,
        provider=PROVIDER,
        external_user_id="fb-1",
        token_encrypted=encrypt("user-token"),
        token_fingerprint=fingerprint("user-token"),
    )
    db.add(connection)
    db.flush()
    return connection


def _account(
    db: Session,
    connection: ProviderConnection,
    external_id: str,
    *,
    owner_business: str = "",
    reached: tuple[str, ...] = (),
    current: bool = False,
) -> AdAccount:
    account = AdAccount(
        owner_id=connection.owner_id,
        provider=PROVIDER,
        external_id=external_id,
        connection_id=connection.id,
        name=external_id,
        currency="USD",
        timezone="Asia/Tashkent",
        may_advertise=True,
        business_external_id=owner_business,
        business_ids=list(reached),
        is_current=current,
        is_active=current,
    )
    db.add(account)
    db.flush()
    return account


def _page(
    db: Session,
    connection: ProviderConnection,
    external_id: str,
    *,
    state: str,
    business: str = "",
    holders: tuple[str, ...] = (),
) -> PageAccount:
    page = PageAccount(
        owner_id=connection.owner_id,
        provider=PROVIDER,
        external_id=external_id,
        connection_id=connection.id,
        name=external_id,
        token_encrypted=b"x",
        token_fingerprint="p",
        is_active=True,
        business_state=state,
        business_external_id=business,
        business_name="Portfolio " + business if business else "",
        business_ids=list(holders or ((business,) if business else ())),
    )
    db.add(page)
    db.flush()
    return page


def _choose(db: Session, user: User, page: str, account: str) -> None:
    cabinet.choose_page_account(
        db, user=user, page_external_id=page, account_external_id=account
    )


def test_a_business_page_takes_its_own_portfolio_and_refuses_another(
    client: TestClient, db: Session
) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    _page(db, connection, "page_a", state="business", business="biz_a")
    _account(db, connection, "act_a", owner_business="biz_a", reached=("biz_a",))
    _account(db, connection, "act_b", owner_business="biz_b", reached=("biz_b",))
    _account(db, connection, "act_me")

    with pytest.raises(AccountNotForPage) as refused:
        _choose(db, user, "page_a", "act_b")
    assert refused.value.code == "account_not_for_page"
    assert refused.value.reason == "other_portfolio"
    with pytest.raises(AccountNotForPage):
        _choose(db, user, "page_a", "act_me")

    _choose(db, user, "page_a", "act_a")
    pair = db.scalar(select(PagePair).where(PagePair.owner_id == user.id))
    assert pair is not None


def test_an_account_shared_into_the_portfolio_fits(
    client: TestClient, db: Session
) -> None:
    """Owned by an agency, shared into the page's portfolio as a client."""
    user, _ = _user(client, db)
    connection = _connection(db, user)
    _page(db, connection, "page_a", state="business", business="biz_a")
    _account(
        db, connection, "act_x", owner_business="agency", reached=("agency", "biz_a")
    )

    _choose(db, user, "page_a", "act_x")


def test_an_agency_client_page_takes_the_agency_accounts(
    client: TestClient, db: Session
) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    _page(
        db,
        connection,
        "page_c",
        state="business",
        business="biz_c",
        holders=("biz_c", "agency"),
    )
    _account(db, connection, "act_ag", owner_business="agency", reached=("agency",))

    _choose(db, user, "page_c", "act_ag")


def test_a_personal_page_takes_only_personal_accounts(
    client: TestClient, db: Session
) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    _page(db, connection, "page_p", state="personal")
    _account(db, connection, "act_a", owner_business="biz_a", reached=("biz_a",))
    _account(db, connection, "act_me")

    with pytest.raises(AccountNotForPage) as refused:
        _choose(db, user, "page_p", "act_a")
    assert refused.value.reason == "not_personal"
    _choose(db, user, "page_p", "act_me")


@pytest.mark.parametrize(
    ("state", "reason"), [("unknown", "page_unknown"), ("", "page_unchecked")]
)
def test_a_page_with_no_known_portfolio_takes_nothing(
    client: TestClient, db: Session, state: str, reason: str
) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    _page(db, connection, "page_u", state=state)
    _account(db, connection, "act_me")

    with pytest.raises(AccountNotForPage) as refused:
        _choose(db, user, "page_u", "act_me")
    assert refused.value.reason == reason
    fit = next(f for f in page_fits(db, owner=user) if f.page == "page_u")
    assert fit.allowed_ad_accounts == ()
    assert fit.blocked_reason == reason
    assert fit.blocked_text


def test_a_pair_made_before_the_rule_is_left_alone(
    client: TestClient, db: Session
) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    page = _page(db, connection, "page_a", state="business", business="biz_a")
    other = _account(
        db, connection, "act_b", owner_business="biz_b", reached=("biz_b",)
    )
    db.add(PagePair(owner_id=user.id, page_id=page.id, ad_account_id=other.id))
    page.ad_account_id = other.id
    db.flush()

    _choose(db, user, "page_a", "act_b")  # no refusal: it was there already
    assert [
        p.account.external_id for p in page_pairs(db, owner=user, pages=[page])
    ] == ["act_b"]


def test_the_cabinet_account_is_lent_only_where_it_fits(
    client: TestClient, db: Session
) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    _account(
        db,
        connection,
        "act_b",
        owner_business="biz_b",
        reached=("biz_b",),
        current=True,
    )
    wrong = _page(db, connection, "page_a", state="business", business="biz_a")
    unread = _page(db, connection, "page_old", state="")
    right = _page(db, connection, "page_b", state="business", business="biz_b")

    pairs = page_pairs(db, owner=user, pages=[wrong, unread, right])

    assert {p.page.external_id for p in pairs} == {"page_old", "page_b"}


def test_the_picker_lists_the_accounts_each_page_takes(
    client: TestClient, db: Session
) -> None:
    user, auth = _user(client, db)
    connection = _connection(db, user)
    _page(db, connection, "page_a", state="business", business="biz_a")
    _page(db, connection, "page_p", state="personal")
    _account(db, connection, "act_a", owner_business="biz_a", reached=("biz_a",))
    _account(db, connection, "act_b", owner_business="biz_b", reached=("biz_b",))
    _account(db, connection, "act_me")
    db.commit()

    answer = client.get("/api/v1/connections", headers=auth)
    assert answer.status_code == 200, answer.text
    fits = {f["page"]: f for f in answer.json()["page_fits"]}
    assert fits["page_a"]["allowed_ad_accounts"] == ["act_a"]
    assert fits["page_a"]["business_name"] == "Portfolio biz_a"
    assert fits["page_a"]["may_create_account"] is True
    assert fits["page_p"]["allowed_ad_accounts"] == ["act_me"]
    assert fits["page_p"]["may_create_account"] is False


def test_store_pages_keeps_the_portfolio(client: TestClient, db: Session) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    found = [
        PageDTO.model_validate(row)
        for row in (
            {
                "id": "p1",
                "tasks": ["MANAGE"],
                "business": {"id": "b1", "name": "Bir"},
                "business_asked": True,
                "client_of": ["ag"],
            },
            {"id": "p2", "tasks": ["MANAGE"], "business_asked": True},
            {"id": "p3", "tasks": ["ADVERTISE"], "business_asked": True},
        )
    ]
    sync.store_pages(db, connection=connection, pages=found)
    rows = {
        p.external_id: p
        for p in db.scalars(select(PageAccount).where(PageAccount.owner_id == user.id))
    }
    assert (rows["p1"].business_state, rows["p1"].business_ids) == (
        "business",
        ["b1", "ag"],
    )
    assert rows["p1"].business_name == "Bir"
    assert rows["p2"].business_state == "personal"
    assert rows["p3"].business_state == "unknown"

    # A later read that could not ask keeps what was learned.
    sync.store_pages(
        db,
        connection=connection,
        pages=[PageDTO.model_validate({"id": "p1", "tasks": ["MANAGE"]})],
    )
    assert rows["p1"].business_state == "business"


def _create(db: Session, user: User, page: str) -> AdAccount:
    return sync.create_ad_account(
        db, user=user, page_external_id=page, name="", currency="usd"
    )


def test_a_new_account_is_made_in_the_portfolio_and_paired(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, auth = _user(client, db)
    connection = _connection(db, user)
    _page(db, connection, "page_a", state="business", business="biz_a")
    db.commit()
    asked: dict[str, Any] = {}

    def made(**kwargs: Any) -> str:
        asked.update(kwargs)
        return "act_new"

    monkeypatch.setattr(sync, "make_ad_account", made)
    monkeypatch.setattr(sync, "sync_ad_accounts", lambda db, connection_id: "0")
    monkeypatch.setattr(settings, "ads_dry_run", False)

    answer = client.post(
        "/api/v1/connections/meta/page/ad-account",
        json={"page": "page_a", "name": "Yangi"},
        headers=auth,
    )

    assert answer.status_code == 200, answer.text
    assert asked["business_id"] == "biz_a"
    assert asked["page_id"] == "page_a"
    assert asked["currency"] == "USD"
    assert asked["timezone_id"] == 336
    account = db.scalar(select(AdAccount).where(AdAccount.external_id == "act_new"))
    assert account is not None
    assert account.business_ids == ["biz_a"]
    pair = db.scalar(select(PagePair).where(PagePair.ad_account_id == account.id))
    assert pair is not None


def test_no_account_is_made_for_a_personal_page(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    _page(db, connection, "page_p", state="personal")
    monkeypatch.setattr(settings, "ads_dry_run", False)

    with pytest.raises(AdAccountNoPortfolio):
        _create(db, user, "page_p")


def test_meta_s_account_limit_reads_as_words(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    _page(db, connection, "page_a", state="business", business="biz_a")
    monkeypatch.setattr(settings, "ads_dry_run", False)

    def refused(**_: Any) -> str:
        raise MetaAPIError("limit", code=3979)

    monkeypatch.setattr(sync, "make_ad_account", refused)
    with pytest.raises(AdAccountLimit):
        _create(db, user, "page_a")


def test_setup_is_not_finished_on_a_page_its_account_does_not_fit(
    client: TestClient, db: Session
) -> None:
    user, _ = _user(client, db)
    connection = _connection(db, user)
    _account(
        db,
        connection,
        "act_b",
        owner_business="biz_b",
        reached=("biz_b",),
        current=True,
    )
    page = _page(db, connection, "page_a", state="business", business="biz_a")
    page.is_current = True
    db.flush()

    with pytest.raises(AccountNotForPage):
        cabinet.pin_shown_pair(db, user=user)


def test_the_start_step_offers_only_the_page_s_portfolio(
    client: TestClient, db: Session
) -> None:
    user, auth = _user(client, db)
    connection = _connection(db, user)
    page = _page(db, connection, "page_a", state="business", business="biz_a")
    page.is_current = True
    _account(db, connection, "act_a", owner_business="biz_a", reached=("biz_a",))
    _account(db, connection, "act_b", owner_business="biz_b", reached=("biz_b",))
    db.commit()

    body = client.get("/api/v1/start", headers=auth).json()

    usable = [
        o["account"]["external_id"]
        for o in body["pick"]["options"]
        if not o["unusable"]
    ]
    assert usable == ["act_a"]
    refused = next(
        o for o in body["pick"]["options"] if o["account"]["external_id"] == "act_b"
    )
    assert refused["not_for_page"] == "other_portfolio"
