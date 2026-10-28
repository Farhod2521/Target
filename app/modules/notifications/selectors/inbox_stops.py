"""The waiting list's lines about advertising that stopped on its own."""

from typing import Final, cast

from adskit import ExternalRef, Level, ProviderName
from metaads.accounts import billing_url
from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.ads.constants import StopReason
from app.modules.ads.models import DeliveryStop
from app.modules.ads.selectors.owned import open_stops, stop_campaigns
from app.modules.notifications.selectors.inbox_page import InboxPage
from core.inbox import InboxItem, Subject

_TITLES: Final[dict[str, str]] = {
    StopReason.ADS_MANAGER: "Reklama Ads Manager'da o'chirildi: «%(name)s»",
    StopReason.CARD_DECLINED: "Reklamalar to'xtadi: Meta kartadan pul yecha olmadi",
    StopReason.BALANCE_USED_UP: (
        "Reklamalar to'xtadi: oldindan to'langan balans tugadi"
    ),
    StopReason.SPEND_CAP: "Reklamalar to'xtadi: akkaunt xarajat chegarasiga yetdi",
    StopReason.PAYMENT_GRACE: (
        "Meta to'lovni o'tkaza olmadi — reklamalar tez orada to'xtaydi"
    ),
    StopReason.PAYMENT_PENDING: "Reklama akkauntida to'lov kutilmoqda",
}

_BODIES: Final[dict[str, str]] = {
    StopReason.ADS_MANAGER: (
        "Bu reklama platformada yaratilgan, lekin uni kimdir Meta Ads Manager'da "
        "to'xtatdi. Bu siz bo'lmasangiz, Ads Manager'ga kirish huquqi kimlarda "
        "borligini tekshiring. Kerak bo'lsa, reklamani shu yerdan qayta yoqing."
    ),
    StopReason.CARD_DECLINED: (
        "Meta «%(account)s» akkauntidagi kartadan pul yecha olmadi, shuning "
        "uchun platformada yaratilgan reklamalar ko'rsatilmayapti. Kartada pul "
        "borligini tekshiring yoki yangi karta qo'shing va qarzni to'lang — "
        "to'lov o'tishi bilan reklamalar o'zi davom etadi."
    ),
    StopReason.BALANCE_USED_UP: (
        "«%(account)s» akkauntiga oldindan to'langan pul tugadi, shuning uchun "
        "reklamalar ko'rsatilmayapti. Balansni to'ldiring — reklamalar o'zi "
        "davom etadi."
    ),
    StopReason.SPEND_CAP: (
        "«%(account)s» akkauntida o'rnatilgan umumiy xarajat chegarasi to'ldi va "
        "Meta reklamalarni to'xtatdi. To'lov sozlamalarida chegarani oshiring "
        "yoki olib tashlang — reklamalar o'zi davom etadi."
    ),
    StopReason.PAYMENT_GRACE: (
        "Meta «%(account)s» akkauntidagi kartadan pul yecha olmadi. Reklamalar "
        "hozircha ishlayapti, lekin to'lov o'tmasa Meta ularni to'xtatadi. "
        "Kartani tekshiring yoki yangisini qo'shing."
    ),
    StopReason.PAYMENT_PENDING: (
        "Meta «%(account)s» akkauntidagi to'lovni hali o'tkazmoqda. Reklamalar "
        "ishlayapti; to'lov o'tmasa, ular to'xtaydi. Kartada pul borligini "
        "tekshirib qo'ying."
    ),
}


def stop_items(db: Session, *, owner: User, view: InboxPage) -> list[InboxItem]:
    """One line per open stop on the accounts that pay for this page."""
    stops = open_stops(db, owner=owner, accounts=view.accounts)
    campaigns = stop_campaigns(db, owner=owner, stops=stops)
    return [stop_item(stop=stop, campaigns=campaigns) for stop in stops]


def stop_item(*, stop: DeliveryStop, campaigns: dict[str, str]) -> InboxItem:
    """The line, and the message - the phone says what the screen says."""
    account = stop.ad_account
    words = {
        "name": stop.name or stop.external_id,
        "account": account.name or account.external_id,
    }
    action, href = _fix(stop=stop, campaigns=campaigns)
    return InboxItem(
        key=f"stop:{stop.id}",
        kind="stop",
        level=("news" if stop.reason == StopReason.PAYMENT_PENDING else "urgent"),
        title=_TITLES[stop.reason] % words,
        body=_BODIES[stop.reason] % words,
        since=stop.detected_at,
        action=action,
        href=href,
        subject=Subject(
            ref=ExternalRef(
                provider=cast("ProviderName", account.provider),
                level=cast("Level", stop.level),
                id=stop.external_id,
            ),
            name=stop.name,
        ),
    )


def _fix(*, stop: DeliveryStop, campaigns: dict[str, str]) -> tuple[str, str]:
    """The one button: the campaign for a switch, the billing page for money."""
    account = stop.ad_account.external_id
    if stop.reason == StopReason.ADS_MANAGER:
        pk = campaigns.get(stop.campaign_external_id)
        href = reverse("ads:campaign", args=[pk]) if pk else reverse("ads:campaigns")
        return "Reklamani ochish", href
    return "To'lov sahifasini ochish", billing_url(account)


__all__ = ["stop_item", "stop_items"]
