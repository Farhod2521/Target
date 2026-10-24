"""The account, page and token a provider call is made with."""

import logging
from typing import Any

from adskit import registry
from sqlalchemy.orm import Session

from app.common.crypto import decrypt
from app.common.exceptions import DecryptionFailed
from app.modules.accounts.models import User
from app.modules.ads.exceptions import (
    ConnectionUnusable,
    LaunchMediaUnsupported,
    LaunchPageGone,
    NoAdAccount,
    NoPage,
)
from app.modules.ads.models import CampaignLaunch, MediaAsset
from app.modules.ads.selectors import account_of
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import AdAccount, PageAccount

logger = logging.getLogger(__name__)


def account_for(db: Session, *, owner: User) -> AdAccount:
    from app.modules.integrations.selectors import active_ad_account

    account = active_ad_account(db, owner=owner)
    if account is None:
        raise NoAdAccount
    return account


def token_for(*, ad_account: AdAccount) -> str:
    connection = ad_account.connection
    if connection is None or connection.status not in USABLE_CONNECTION_STATUSES:
        raise ConnectionUnusable
    try:
        stored = decrypt(connection.token_encrypted)
    except DecryptionFailed as exc:
        logger.exception("connection %s could not be decrypted", connection.id)
        raise ConnectionUnusable from exc
    return registry.get(ad_account.provider).connect.access_token(stored=stored)


def account_and_token(db: Session, *, owner: User) -> tuple[AdAccount, str]:
    account = account_for(db, owner=owner)
    return account, token_for(ad_account=account)


def target_account_and_token(*, target: Any, level: str) -> tuple[AdAccount, str]:
    account = account_of(target=target, level=level)
    if not account.is_active:
        raise NoAdAccount
    return account, token_for(ad_account=account)


def launch_account_and_token(
    db: Session, *, launch: CampaignLaunch
) -> tuple[AdAccount, str]:
    account = db.get(AdAccount, launch.ad_account_id)
    if account is None:
        raise NoAdAccount
    return account, token_for(ad_account=account)


def page_for(db: Session, *, owner: User) -> PageAccount:
    from app.modules.integrations.selectors import active_page

    page = active_page(db, owner=owner)
    if page is None:
        raise NoPage
    return page


def page_and_token(db: Session, *, owner: User) -> tuple[PageAccount, str]:
    page = page_for(db, owner=owner)
    return page, _decrypted(page)


def launch_page(db: Session, *, launch: CampaignLaunch) -> PageAccount | None:
    from app.modules.integrations.selectors import active_page

    if launch.page_id is not None:
        return launch.page
    return active_page(db, owner=launch.owner)


def _fresh_launch_page(db: Session, launch: CampaignLaunch) -> PageAccount | None:
    page = launch_page(db, launch=launch)
    if page is not None:
        db.refresh(page)
    return page


def launch_page_for(db: Session, *, launch: CampaignLaunch) -> PageAccount:
    page = _fresh_launch_page(db, launch)
    if page is None:
        raise NoPage
    if not page.is_active:
        raise LaunchPageGone
    return page


def launch_page_and_token(
    db: Session, *, launch: CampaignLaunch
) -> tuple[PageAccount, str]:
    page = launch_page_for(db, launch=launch)
    return page, _decrypted(page)


def launch_page_token(db: Session, *, launch: CampaignLaunch) -> str:
    page = _fresh_launch_page(db, launch)
    if page is None:
        raise NoPage
    return _decrypted(page)


def _decrypted(page: PageAccount) -> str:
    try:
        return decrypt(page.token_encrypted)
    except DecryptionFailed as exc:
        logger.exception("page token %s could not be decrypted", page.id)
        raise ConnectionUnusable from exc


def profile_token(asset: MediaAsset) -> str:
    page = asset.page
    if page is None:
        raise LaunchMediaUnsupported
    return _decrypted(page)
