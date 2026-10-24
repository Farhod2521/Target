"""Which pages and accounts are in the subscription, and which one is being shown."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from googleadskit import PROVIDER as GOOGLE
from metaads import PROVIDER
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.integrations.exceptions import (
    AccountAlreadyBound,
    AccountCannotAdvertise,
    AccountLocked,
    AlreadyEnabled,
    GoogleAccountCannotAdvertise,
    GoogleAccountNotInSubscription,
    GoogleAdsUnavailable,
    GoogleNoFreeSlot,
    InstagramLocked,
    NoFreeSlot,
    NoPageChosen,
    NothingToRebind,
    PageAlreadyChosen,
    PageLocked,
    PageNotInCabinet,
    PairExists,
    PairLocked,
    SubscriptionRequired,
    UnknownAccount,
    UnknownInstagram,
)
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PageInstagram,
    PagePair,
    PixelAccount,
)
from app.modules.integrations.selectors import (
    active_ad_account,
    active_page,
    current_pair,
    google_ads_on,
    google_slots,
    page_ad_account,
    page_pairs,
    page_slots,
    pair_for,
)
from app.modules.integrations.services.sync import clear_extra_instagrams

logger = logging.getLogger(__name__)
PAGE = "page"
GOOGLE_ACCOUNT = "google_account"
SUBSCRIPTION = "subscription"


def _billing():  # type: ignore[no-untyped-def]
    from app.modules.billing import selectors

    return selectors


def _read_the_account(db: Session, account: AdAccount) -> None:
    from app.modules.ads.tasks import sync_ad_account_task, sync_media_task
    from app.modules.integrations.tasks import sync_pixels_task
    from app.modules.metrics.tasks import sync_insights_task

    key = str(account.id)
    on_commit(db, lambda: sync_ad_account_task.delay(key))
    on_commit(db, lambda: sync_insights_task.delay(key))
    on_commit(db, lambda: sync_pixels_task.delay(key))
    on_commit(db, lambda: sync_media_task.delay(key))


def queue_page_follow_ups(db: Session, *, user: User, page: PageAccount) -> None:
    from app.modules.ads.tasks import sync_owner_media_task
    from app.modules.integrations.tasks import sync_pages_task
    from app.modules.leads.tasks import (
        reconcile_page_task,
        subscribe_page_task,
        sync_page_forms_task,
    )

    connection_id, page_id, owner_id = (
        str(page.connection_id),
        str(page.id),
        str(user.id),
    )
    on_commit(db, lambda: sync_pages_task.delay(connection_id))
    on_commit(db, lambda: subscribe_page_task.delay(page_id))
    on_commit(db, lambda: sync_page_forms_task.delay(page_id))
    on_commit(db, lambda: reconcile_page_task.delay(page_id))
    on_commit(db, lambda: sync_owner_media_task.delay(owner_id))


def apply_page_choice(db: Session, *, user: User, page: PageAccount) -> PageAccount:
    from app.modules.businesses.services import adopt_page

    db.refresh(page, ["is_active", "is_current"])
    arriving = not page.is_active
    previous = db.scalar(
        select(PageAccount).where(
            PageAccount.owner_id == user.id,
            PageAccount.provider == PROVIDER,
            PageAccount.is_current.is_(True),
            PageAccount.id != page.id,
        )
    )
    if previous is not None:
        previous.is_current = False
        previous.is_active = previous.is_active and not arriving
        db.flush()
    page.is_active = True
    page.is_current = True
    db.flush()
    if arriving:
        clear_extra_instagrams(db, page=page)
    adopt_page(db, user=user, page=page)
    queue_page_follow_ups(db, user=user, page=page)
    return page


def enable_page(db: Session, *, user: User, external_id: str) -> PageAccount:
    page = db.scalar(
        select(PageAccount)
        .where(
            PageAccount.owner_id == user.id,
            PageAccount.provider == PROVIDER,
            PageAccount.external_id == external_id,
        )
        .with_for_update()
    )
    if page is None:
        raise UnknownAccount
    if page.is_active:
        raise AlreadyEnabled
    if _billing().live_subscription(db, owner=user) is None:
        raise SubscriptionRequired
    if not page_slots(db, owner=user).has_room:
        raise NoFreeSlot(noun="sahifa")
    page.is_active = True
    page.is_current = active_page(db, owner=user) is None
    if page.is_current:
        db.execute(
            update(PageAccount)
            .where(
                PageAccount.owner_id == user.id,
                PageAccount.provider == PROVIDER,
                PageAccount.is_current.is_(True),
                PageAccount.id != page.id,
            )
            .values(is_current=False)
        )
    db.flush()
    clear_extra_instagrams(db, page=page)
    queue_page_follow_ups(db, user=user, page=page)
    emit(
        db,
        owner_id=user.id,
        name=EventName.PAGE_ENABLED,
        aggregate_type=PAGE,
        aggregate_id=page.id,
        payload={
            "external_id": page.external_id,
            "provider": page.provider,
            "is_current": page.is_current,
        },
    )
    logger.info("page %s added to the cabinet of %s", page.external_id, user.id)
    return page


def enable_pages(
    db: Session, *, user: User, external_ids: Sequence[str]
) -> list[PageAccount]:
    wanted = list(
        dict.fromkeys(external_id for external_id in external_ids if external_id)
    )
    if not wanted:
        raise NoPageChosen
    if _billing().live_subscription(db, owner=user) is None:
        raise SubscriptionRequired
    if len(wanted) > page_slots(db, owner=user).free:
        raise NoFreeSlot(noun="sahifa")
    return [
        enable_page(db, user=user, external_id=external_id) for external_id in wanted
    ]


def add_page(
    db: Session, *, user: User, page_external_id: str, account_external_id: str
) -> PageAccount:
    page = enable_page(db, user=user, external_id=page_external_id)
    if not account_external_id:
        return page
    return choose_page_account(
        db,
        user=user,
        page_external_id=page.external_id,
        account_external_id=account_external_id,
    )


def take_promo_pages(
    db: Session,
    *,
    user: User,
    external_ids: Sequence[str],
    redemption_id: str,
    now: datetime,
) -> list[PageAccount]:
    from app.modules.billing.services import acknowledge_promo

    pages = enable_pages(db, user=user, external_ids=external_ids)
    acknowledge_promo(db, owner=user, redemption_id=redemption_id, now=now)
    logger.info(
        "promo announcement %s answered with %s pages", redemption_id, len(pages)
    )
    return pages


def _instagram_row(
    db: Session, *, user: User, page_external_id: str, instagram_user_id: str
) -> PageInstagram:
    row = db.scalar(
        select(PageInstagram)
        .join(PageAccount, PageAccount.id == PageInstagram.page_id)
        .where(
            PageInstagram.owner_id == user.id,
            PageAccount.provider == PROVIDER,
            PageAccount.external_id == page_external_id,
            PageAccount.is_active.is_(True),
            PageInstagram.instagram_user_id == instagram_user_id,
        )
        .with_for_update(of=PageInstagram)
    )
    if row is None or row.is_page_own:
        raise UnknownInstagram
    return row


def enable_instagram(
    db: Session, *, user: User, page_external_id: str, instagram_user_id: str
) -> PageInstagram:
    from app.modules.ads.tasks import sync_owner_media_task

    row = _instagram_row(
        db,
        user=user,
        page_external_id=page_external_id,
        instagram_user_id=instagram_user_id,
    )
    if row.is_active:
        raise AlreadyEnabled
    if not row.is_linked:
        raise UnknownInstagram
    if _billing().live_subscription(db, owner=user) is None:
        raise SubscriptionRequired
    if not page_slots(db, owner=user).has_room:
        raise NoFreeSlot(noun="Instagram akkaunti")
    row.is_active = True
    owner_id = str(user.id)
    on_commit(db, lambda: sync_owner_media_task.delay(owner_id))
    emit(
        db,
        owner_id=user.id,
        name=EventName.INSTAGRAM_ENABLED,
        aggregate_type="page_instagram",
        aggregate_id=row.id,
        payload={
            "page": row.page.external_id,
            "instagram_user_id": row.instagram_user_id,
        },
    )
    db.flush()
    return row


def disable_instagram(
    db: Session, *, user: User, page_external_id: str, instagram_user_id: str
) -> PageInstagram:
    if _billing().setup_locked(db, owner=user):
        raise InstagramLocked
    row = _instagram_row(
        db,
        user=user,
        page_external_id=page_external_id,
        instagram_user_id=instagram_user_id,
    )
    if not row.is_active:
        return row
    row.is_active = False
    emit(
        db,
        owner_id=user.id,
        name=EventName.INSTAGRAM_DISABLED,
        aggregate_type="page_instagram",
        aggregate_id=row.id,
        payload={
            "page": row.page.external_id,
            "instagram_user_id": row.instagram_user_id,
        },
    )
    db.flush()
    return row


def enable_google_account(db: Session, *, user: User, external_id: str) -> AdAccount:
    from app.modules.ads.tasks import sync_ad_account_task
    from app.modules.businesses.services import seed_google_profile
    from app.modules.metrics.tasks import sync_insights_task

    if not google_ads_on(user=user):
        raise GoogleAdsUnavailable
    account = db.scalar(
        select(AdAccount)
        .where(
            AdAccount.owner_id == user.id,
            AdAccount.provider == GOOGLE,
            AdAccount.external_id == external_id,
        )
        .with_for_update()
    )
    if account is None:
        raise UnknownAccount
    if account.may_advertise is False:
        raise GoogleAccountCannotAdvertise
    if account.is_active:
        raise AlreadyEnabled
    if _billing().live_subscription(db, owner=user) is None:
        raise SubscriptionRequired
    if not google_slots(db, owner=user).has_room:
        raise GoogleNoFreeSlot
    account.is_active = True
    account.is_current = not db.scalar(
        select(AdAccount.id).where(
            AdAccount.owner_id == user.id,
            AdAccount.provider == GOOGLE,
            AdAccount.is_active.is_(True),
            AdAccount.is_current.is_(True),
            AdAccount.id != account.id,
        )
    )
    if account.is_current:
        db.execute(
            update(AdAccount)
            .where(
                AdAccount.owner_id == user.id,
                AdAccount.provider == GOOGLE,
                AdAccount.is_current.is_(True),
                AdAccount.id != account.id,
            )
            .values(is_current=False)
        )
    db.flush()
    seed_google_profile(db, user=user, account=account)
    emit(
        db,
        owner_id=user.id,
        name=EventName.GOOGLE_ACCOUNT_ENABLED,
        aggregate_type=GOOGLE_ACCOUNT,
        aggregate_id=account.id,
        payload={
            "external_id": account.external_id,
            "provider": account.provider,
            "is_current": account.is_current,
        },
    )
    key = str(account.id)
    on_commit(db, lambda: sync_ad_account_task.delay(key))
    on_commit(db, lambda: sync_insights_task.delay(key))
    return account


def select_google_account(db: Session, *, user: User, external_id: str) -> AdAccount:
    if not google_ads_on(user=user):
        raise GoogleAdsUnavailable
    account = db.scalar(
        select(AdAccount)
        .where(
            AdAccount.owner_id == user.id,
            AdAccount.provider == GOOGLE,
            AdAccount.external_id == external_id,
        )
        .with_for_update()
    )
    if account is None:
        raise UnknownAccount
    if not account.is_active:
        raise GoogleAccountNotInSubscription
    db.execute(
        update(AdAccount)
        .where(
            AdAccount.owner_id == user.id,
            AdAccount.provider == GOOGLE,
            AdAccount.is_current.is_(True),
            AdAccount.id != account.id,
        )
        .values(is_current=False)
    )
    account.is_current = True
    db.flush()
    return account


def select_ad_account(db: Session, *, user: User, external_id: str) -> AdAccount:
    billing = _billing()
    if billing.setup_locked(db, owner=user):
        raise AccountLocked
    if not billing.may_prepare(db, owner=user):
        raise SubscriptionRequired
    subscription = billing.live_subscription(db, owner=user)
    account = db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == user.id,
            AdAccount.provider == PROVIDER,
            AdAccount.external_id == external_id,
        )
    )
    if account is None:
        raise UnknownAccount
    if account.may_advertise is False and not account.payment_due:
        raise AccountCannotAdvertise
    db.execute(
        update(AdAccount)
        .where(
            AdAccount.owner_id == user.id,
            AdAccount.provider == PROVIDER,
            AdAccount.id != account.id,
            or_(AdAccount.is_active.is_(True), AdAccount.is_current.is_(True)),
        )
        .values(is_active=False, is_current=False)
    )
    account.is_active = True
    account.is_current = True
    if subscription is not None:
        subscription.ad_account_id = account.id
    db.flush()
    _read_the_account(db, account)
    return account


def select_page(db: Session, *, user: User, external_id: str) -> PageAccount:
    if _billing().setup_locked(db, owner=user):
        raise PageLocked
    page = db.scalar(
        select(PageAccount)
        .where(
            PageAccount.owner_id == user.id,
            PageAccount.provider == PROVIDER,
            PageAccount.external_id == external_id,
        )
        .with_for_update()
    )
    if page is None:
        raise UnknownAccount
    page = apply_page_choice(db, user=user, page=page)
    db.refresh(page, ["ad_account_id"])
    payer = page.ad_account
    if payer is not None and not payer.is_current:
        try:
            select_ad_account(db, user=user, external_id=payer.external_id)
        except (AccountCannotAdvertise, SubscriptionRequired):
            pass
    return page


def select_pixel(db: Session, *, user: User, external_id: str) -> PixelAccount:
    account = active_ad_account(db, owner=user)
    if account is None:
        raise UnknownAccount
    pixel = db.scalar(
        select(PixelAccount).where(
            PixelAccount.owner_id == user.id,
            PixelAccount.provider == PROVIDER,
            PixelAccount.ad_account_id == account.id,
            PixelAccount.external_id == external_id,
        )
    )
    if pixel is None:
        raise UnknownAccount
    db.execute(
        update(PixelAccount)
        .where(
            PixelAccount.owner_id == user.id,
            PixelAccount.provider == PROVIDER,
            PixelAccount.ad_account_id == account.id,
            PixelAccount.is_active.is_(True),
        )
        .values(is_active=False)
    )
    pixel.is_active = True
    db.flush()
    return pixel


def _make_current(
    db: Session,
    *,
    model: type[AdAccount] | type[PageAccount],
    owner: User,
    row: AdAccount | PageAccount,
) -> None:
    db.execute(
        update(model)
        .where(
            model.owner_id == owner.id,
            model.provider == PROVIDER,
            model.is_current.is_(True),
            model.id != row.id,
        )
        .values(is_current=False)
    )
    row.is_current = True
    db.flush()


def bring_in_account(db: Session, *, user: User, account: AdAccount) -> None:
    if account.is_active:
        return
    if _billing().live_subscription(db, owner=user) is None:
        raise SubscriptionRequired
    account.is_active = True
    db.flush()
    _read_the_account(db, account)


def switch_ad_account(db: Session, *, user: User, external_id: str) -> AdAccount:
    account = db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == user.id,
            AdAccount.provider == PROVIDER,
            AdAccount.external_id == external_id,
        )
    )
    if account is None:
        raise UnknownAccount
    if account.is_current:
        return account
    bring_in_account(db, user=user, account=account)
    _make_current(db, model=AdAccount, owner=user, row=account)
    logger.info("cabinet of %s now showing %s", user.id, account.external_id)
    return account


def switch_page(db: Session, *, user: User, external_id: str) -> PageAccount:
    page = db.scalar(
        select(PageAccount).where(
            PageAccount.owner_id == user.id,
            PageAccount.provider == PROVIDER,
            PageAccount.external_id == external_id,
            PageAccount.is_active.is_(True),
        )
    )
    if page is None:
        raise UnknownAccount
    if page.is_current:
        return page
    _make_current(db, model=PageAccount, owner=user, row=page)
    follow_page_payer(db, user=user, page=page)
    return page


def follow_page_payer(db: Session, *, user: User, page: PageAccount) -> None:
    payer = page_ad_account(db, owner=user, page=page)
    if payer is None or payer.is_current:
        return
    try:
        switch_ad_account(db, user=user, external_id=payer.external_id)
    except SubscriptionRequired:
        logger.info(
            "page %s pays from %s, which a lapsed cabinet cannot bring back",
            page.external_id,
            payer.external_id,
        )


def make_page_current(db: Session, *, user: User, page: PageAccount) -> None:
    if not page.is_current:
        _make_current(db, model=PageAccount, owner=user, row=page)


def page_and_account(
    db: Session, *, owner: User, page_external_id: str, account_external_id: str
) -> tuple[PageAccount, AdAccount]:
    page = db.scalar(
        select(PageAccount).where(
            PageAccount.owner_id == owner.id,
            PageAccount.provider == PROVIDER,
            PageAccount.external_id == page_external_id,
            PageAccount.is_active.is_(True),
        )
    )
    account = db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == PROVIDER,
            AdAccount.external_id == account_external_id,
        )
    )
    if page is None or account is None:
        raise UnknownAccount
    if account.may_advertise is False and not account.payment_due:
        raise AccountCannotAdvertise
    return page, account


def _pairs_of(db: Session, *, owner: User, page: PageAccount) -> list[PagePair]:
    return list(
        db.scalars(
            select(PagePair)
            .where(PagePair.owner_id == owner.id, PagePair.page_id == page.id)
            .order_by(PagePair.created_at)
            .with_for_update()
        )
    )


def choose_page_account(
    db: Session, *, user: User, page_external_id: str, account_external_id: str
) -> PageAccount:
    page, account = page_and_account(
        db,
        owner=user,
        page_external_id=page_external_id,
        account_external_id=account_external_id,
    )
    locked = _billing().setup_locked(db, owner=user)
    pairs = _pairs_of(db, owner=user, page=page)
    if any(pair.ad_account_id == account.id for pair in pairs):
        if locked:
            return page
    elif pairs and locked:
        raise PairLocked
    elif pairs:
        pairs[0].ad_account_id = account.id
    else:
        db.add(PagePair(owner_id=user.id, page_id=page.id, ad_account_id=account.id))
    page.ad_account_id = account.id
    db.flush()
    if page.is_current and not account.is_current:
        if locked:
            switch_ad_account(db, user=user, external_id=account.external_id)
        else:
            select_ad_account(db, user=user, external_id=account.external_id)
    elif locked:
        bring_in_account(db, user=user, account=account)
    emit(
        db,
        owner_id=user.id,
        name=EventName.PAGE_PAYER_CHOSEN,
        aggregate_type=PAGE,
        aggregate_id=page.id,
        payload={
            "page": page.external_id,
            "ad_account": account.external_id,
            "provider": page.provider,
        },
    )
    return page


def _show(db: Session, *, user: User, page: PageAccount, account: AdAccount) -> None:
    make_page_current(db, user=user, page=page)
    switch_ad_account(db, user=user, external_id=account.external_id)


def add_page_pair(
    db: Session, *, user: User, page_external_id: str, account_external_id: str
) -> PagePair:
    page, account = page_and_account(
        db,
        owner=user,
        page_external_id=page_external_id,
        account_external_id=account_external_id,
    )
    if not _billing().setup_locked(db, owner=user):
        choose_page_account(
            db,
            user=user,
            page_external_id=page_external_id,
            account_external_id=account_external_id,
        )
        found = db.scalar(
            select(PagePair).where(
                PagePair.owner_id == user.id, PagePair.page_id == page.id
            )
        )
        assert found is not None
        return found
    known = _pairs_of(db, owner=user, page=page)
    if any(pair.ad_account_id == account.id for pair in known):
        raise PairExists
    if not known:
        today = page_pairs(db, owner=user, pages=[page])
        if today and today[0].account.id != account.id:
            db.add(
                PagePair(
                    owner_id=user.id, page_id=page.id, ad_account_id=today[0].account.id
                )
            )
    pair = PagePair(owner_id=user.id, page_id=page.id, ad_account_id=account.id)
    db.add(pair)
    if page.ad_account_id is None:
        page.ad_account_id = account.id
    db.flush()
    _show(db, user=user, page=page, account=account)
    emit(
        db,
        owner_id=user.id,
        name=EventName.PAGE_PAIR_ADDED,
        aggregate_type=PAGE,
        aggregate_id=page.id,
        payload={
            "page": page.external_id,
            "ad_account": account.external_id,
            "provider": page.provider,
        },
    )
    return pair


def pin_shown_pair(db: Session, *, user: User) -> PagePair | None:
    pair = current_pair(db, owner=user)
    if pair is None or pair.stored:
        return None
    stored = PagePair(
        owner_id=user.id, page_id=pair.page.id, ad_account_id=pair.account.id
    )
    db.add(stored)
    if pair.page.ad_account_id is None:
        pair.page.ad_account_id = pair.account.id
    db.flush()
    return stored


def switch_pair(
    db: Session, *, user: User, page_external_id: str, account_external_id: str
) -> PageAccount:
    pair = pair_for(
        db,
        owner=user,
        page_external_id=page_external_id,
        account_external_id=account_external_id,
    )
    if pair is None:
        raise UnknownAccount
    _show(db, user=user, page=pair.page, account=pair.account)
    return pair.page


def change_pair_account(
    db: Session,
    *,
    owner: User,
    page_external_id: str,
    from_external_id: str,
    to_external_id: str,
    actor: User,
) -> PagePair:
    page, account = page_and_account(
        db,
        owner=owner,
        page_external_id=page_external_id,
        account_external_id=to_external_id,
    )
    pairs = _pairs_of(db, owner=owner, page=page)
    if any(pair.ad_account_id == account.id for pair in pairs):
        raise PairExists
    pair = next(
        (p for p in pairs if p.ad_account.external_id == from_external_id), None
    )
    if pair is None and pairs:
        raise UnknownAccount
    was_current = page.is_current and (pair is None or pair.ad_account.is_current)
    if pair is None:
        pair = PagePair(owner_id=owner.id, page_id=page.id, ad_account_id=account.id)
        db.add(pair)
        pairs.append(pair)
    else:
        pair.ad_account_id = account.id
    db.flush()
    if pairs and pairs[0] is pair:
        page.ad_account_id = account.id
    db.flush()
    if was_current:
        switch_ad_account(db, user=owner, external_id=account.external_id)
    else:
        bring_in_account(db, user=owner, account=account)
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PAGE_PAIR_CHANGED,
        aggregate_type=PAGE,
        aggregate_id=page.id,
        payload={
            "page": page.external_id,
            "from_ad_account": from_external_id,
            "ad_account": account.external_id,
            "provider": page.provider,
            "actor_id": str(actor.id),
        },
    )
    return pair


def remove_page_pair(
    db: Session,
    *,
    owner: User,
    page_external_id: str,
    account_external_id: str,
    actor: User,
) -> None:
    page, account = page_and_account(
        db,
        owner=owner,
        page_external_id=page_external_id,
        account_external_id=account_external_id,
    )
    pairs = _pairs_of(db, owner=owner, page=page)
    pair = next((p for p in pairs if p.ad_account_id == account.id), None)
    if pair is None:
        raise UnknownAccount
    was_current = page.is_current and account.is_current
    db.delete(pair)
    db.flush()
    left = next((p for p in pairs if p is not pair), None)
    if page.ad_account_id == account.id:
        page.ad_account_id = left.ad_account_id if left is not None else None
        db.flush()
    if was_current and left is not None:
        switch_ad_account(db, user=owner, external_id=left.ad_account.external_id)
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PAGE_PAIR_REMOVED,
        aggregate_type=PAGE,
        aggregate_id=page.id,
        payload={
            "page": page.external_id,
            "ad_account": account.external_id,
            "provider": page.provider,
            "actor_id": str(actor.id),
        },
    )


def rebind_ad_account(
    db: Session, *, owner: User, external_id: str, actor: User
) -> AdAccount:
    account = db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == PROVIDER,
            AdAccount.external_id == external_id,
        )
    )
    if account is None:
        raise UnknownAccount
    subscription = _billing().bound_subscription(db, owner=owner)
    if subscription is None:
        raise NothingToRebind
    previous = (
        db.get(AdAccount, subscription.ad_account_id)
        if subscription.ad_account_id
        else None
    )
    if previous is not None and previous.id == account.id:
        raise AccountAlreadyBound
    db.execute(
        update(AdAccount)
        .where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == PROVIDER,
            AdAccount.id != account.id,
            or_(AdAccount.is_active.is_(True), AdAccount.is_current.is_(True)),
        )
        .values(is_active=False, is_current=False)
    )
    account.is_active = True
    account.is_current = True
    subscription.ad_account_id = account.id
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.ACCOUNT_REBOUND,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id,
        payload={
            "from_external_id": previous.external_id if previous else "",
            "to_external_id": account.external_id,
            "provider": PROVIDER,
            "actor_id": str(actor.id),
        },
    )
    _read_the_account(db, account)
    return account


def rebind_summary(
    *, owner: User, previous: AdAccount | None, account: AdAccount
) -> str:
    return "%(owner)s: %(before)s → %(after)s" % {
        "owner": owner.email,
        "before": previous.external_id if previous else "-",
        "after": account.external_id,
    }


def rebind_page(db: Session, *, page: PageAccount, actor: User) -> PageAccount:
    owner = db.get(User, page.owner_id)
    assert owner is not None
    previous = active_page(db, owner=owner)
    db.refresh(page, ["is_active", "is_current"])
    if page.is_active and page.is_current:
        raise PageAlreadyChosen
    moved = apply_page_choice(db, user=owner, page=page)
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PAGE_REBOUND,
        aggregate_type=PAGE,
        aggregate_id=moved.id,
        payload={
            "from_external_id": previous.external_id if previous else "",
            "to_external_id": moved.external_id,
            "provider": moved.provider,
            "actor_id": str(actor.id),
        },
    )
    return moved


def rebind_page_summary(
    *, owner: User, previous: PageAccount | None, page: PageAccount
) -> str:
    return "%(owner)s: %(before)s → %(after)s" % {
        "owner": owner.email,
        "before": str(previous) if previous else "-",
        "after": str(page),
    }


@dataclass(frozen=True, slots=True)
class Released:
    page: PageAccount
    successor: PageAccount | None
    emptied: bool


def release_page(
    db: Session, *, page: PageAccount, actor: User, now: datetime
) -> Released:
    if not page.is_active:
        raise PageNotInCabinet
    owner_id = page.owner_id
    was_current = page.is_current
    page.is_active = False
    page.is_current = False
    db.flush()
    successor: PageAccount | None = None
    if was_current:
        successor = db.scalar(
            select(PageAccount)
            .where(
                PageAccount.owner_id == owner_id,
                PageAccount.provider == PROVIDER,
                PageAccount.is_active.is_(True),
            )
            .order_by(PageAccount.name)
            .limit(1)
        )
        if successor is not None:
            successor.is_current = True
            db.flush()
    emit(
        db,
        owner_id=owner_id,
        name=EventName.PAGE_RELEASED,
        aggregate_type=PAGE,
        aggregate_id=page.id,
        payload={
            "external_id": page.external_id,
            "provider": page.provider,
            "was_current": was_current,
            "successor_external_id": successor.external_id if successor else "",
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    emptied = not db.scalar(
        select(PageAccount.id)
        .where(
            PageAccount.owner_id == owner_id,
            PageAccount.provider == PROVIDER,
            PageAccount.is_active.is_(True),
        )
        .limit(1)
    )
    return Released(page=page, successor=successor, emptied=emptied)


def release_summary(*, owner: User, released: Released) -> str:
    page = released.page
    if released.emptied:
        return (
            "%(owner)s: %(page)s uzildi. Kabinetda sahifa qolmadi — "
            "mijoz «Ulanishlar» ekranidan yangisini qo'shishi kerak."
        ) % {"owner": owner.email, "page": str(page)}
    return "%(owner)s: %(page)s uzildi. O'rin bo'shadi." % {
        "owner": owner.email,
        "page": str(page),
    }


@dataclass(frozen=True, slots=True)
class GoogleReleased:
    account: AdAccount
    successor: AdAccount | None


def release_google_account(
    db: Session, *, account: AdAccount, actor: User, now: datetime
) -> GoogleReleased:
    if account.provider != GOOGLE or not account.is_active:
        raise GoogleAccountNotInSubscription
    was_current = account.is_current
    account.is_active = False
    account.is_current = False
    db.flush()
    successor: AdAccount | None = None
    if was_current:
        successor = db.scalar(
            select(AdAccount)
            .where(
                AdAccount.owner_id == account.owner_id,
                AdAccount.provider == GOOGLE,
                AdAccount.is_active.is_(True),
            )
            .order_by(AdAccount.name)
            .limit(1)
        )
        if successor is not None:
            successor.is_current = True
            db.flush()
    emit(
        db,
        owner_id=account.owner_id,
        name=EventName.GOOGLE_ACCOUNT_RELEASED,
        aggregate_type=GOOGLE_ACCOUNT,
        aggregate_id=account.id,
        payload={
            "external_id": account.external_id,
            "was_current": was_current,
            "successor_external_id": successor.external_id if successor else "",
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    return GoogleReleased(account=account, successor=successor)


def google_release_summary(*, owner: User, released: GoogleReleased) -> str:
    return "%(owner)s: %(account)s obunadan chiqarildi. O'rin bo'shadi." % {
        "owner": owner.email,
        "account": str(released.account),
    }


def swap_page(
    db: Session, *, source: PageAccount, target: PageAccount, actor: User, now: datetime
) -> PageAccount:
    from app.modules.businesses.services import adopt_page

    db.refresh(source, ["is_active", "is_current"])
    db.refresh(target, ["is_active", "is_current"])
    if not source.is_active or source.owner_id != target.owner_id:
        raise PageNotInCabinet
    if target.is_active:
        raise AlreadyEnabled
    owner = db.get(User, source.owner_id)
    assert owner is not None
    current = source.is_current
    source.is_active = False
    source.is_current = False
    db.flush()
    target.is_active = True
    target.is_current = current
    db.flush()
    if current:
        adopt_page(db, user=owner, page=target)
    queue_page_follow_ups(db, user=owner, page=target)
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PAGE_REBOUND,
        aggregate_type=PAGE,
        aggregate_id=target.id,
        payload={
            "external_id": target.external_id,
            "provider": target.provider,
            "previous_external_id": source.external_id,
            "is_current": current,
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    return target
