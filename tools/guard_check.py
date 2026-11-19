"""The half-hourly guard, now, for one owner - to try it on a real account.

    docker compose exec api python -m tools.guard_check <email>            # the real pass
    docker compose exec api python -m tools.guard_check <email> --look     # only shows, writes nothing

What the real pass does is what the schedule does at :21 and :51 for this
owner, in the same order:

1. every enabled ad account whose figures are over an hour old is read from
   Meta first (the objects, then today's figures) - ``--no-sync`` skips it,
   and such an account is then left out, as the schedule leaves it out;
2. the guard judges every running group of the owner's page and ad account
   pairs (``run_guard``): findings are written, and a stop is asked of Meta
   when the owner has the agent on - ``--no-stop`` turns every stop into a
   warning, as for an owner who switched the agent off;
3. the linked Telegram is sent the new findings (``--no-telegram`` skips
   it). Warnings keep their rules: before the morning report hour they
   wait (``--ignore-night`` sends them anyway), a group gets one a day, and
   at most three go in one pass. A stop is said once Meta answered it - the
   worker sends that message by itself.

``--look`` reads (and syncs, unless ``--no-sync``) and prints what the rules
find for each group, without writing a finding, stopping or sending.
"""

import argparse
import sys

from sqlalchemy import func, select

from app import models as _models  # noqa: F401
from app.common.db import utcnow
from app.common.i18n import override
from app.modules.accounts.models import User
from app.modules.agent.guard_copy import guard_body, guard_title
from app.modules.agent.models import GuardAlert
from app.worker import task_session


def _owner(db, email: str) -> User | None:
    return db.scalar(
        select(User).where(func.lower(User.email) == email.strip().lower())
    )


def _sync(db, account) -> str:
    from app.modules.ads.exceptions import SyncAlreadyRunning
    from app.modules.ads.services.mirror import sync_ad_account
    from app.modules.metrics.services.sync import sync_today

    try:
        sync_ad_account(db, ad_account=account, whole=False)
        db.commit()
        summary = sync_today(db, ad_account=account)
        db.commit()
    except SyncAlreadyRunning:
        db.rollback()
        return "sinxron allaqachon ketyapti - tugashini kuting va qayta ishga tushiring"
    except Exception as exc:
        db.rollback()
        return f"Meta'dan o'qib bo'lmadi: {type(exc).__name__}: {exc}"
    db.expire_all()
    return f"o'qildi ({'to`liq' if summary.complete else 'qisman'})"


def _accounts(db, owner, *, now, sync: bool) -> list:
    from app.modules.agent.selectors.guard import fresh
    from app.modules.integrations.selectors.slots import enabled_ad_accounts

    ready = []
    for account in enabled_ad_accounts(db, owner=owner):
        label = f"{account.name or account.external_id} ({account.external_id})"
        if fresh(db, owner=owner, account=account, now=now):
            print(f"  {label}: raqamlar yangi (1 soat ichida o'qilgan)")
            ready.append(account)
            continue
        if not sync:
            print(f"  {label}: raqamlar 1 soatdan eski - tashlab ketildi (--no-sync)")
            continue
        said = _sync(db, account)
        if fresh(db, owner=owner, account=account, now=utcnow()):
            print(f"  {label}: {said}")
            ready.append(account)
        else:
            print(f"  {label}: {said}; raqamlar hali eski - tashlab ketildi")
    return ready


def _look(db, owner, accounts, *, now) -> None:
    from app.modules.ads.selectors.pages import page_scope
    from app.modules.agent.selectors.guard import guarded_groups
    from app.modules.agent.services.run_guard import in_pair
    from core.agent.guard import judge, price_times

    scope = page_scope(db, owner=owner)
    for account in accounts:
        print(f"\n== {account.name or account.external_id} ==")
        groups = guarded_groups(db, owner=owner, account=account, now=now, baselines={})
        if not groups:
            print("  ishlayotgan guruh yo'q")
        for item in groups:
            group = item.group
            where = (
                "juftlikda"
                if in_pair(scope, account=account, adset_id=group.adset_id)
                else "JUFTLIKDA EMAS - tekshirilmaydi"
            )
            usual = group.usual.cost_minor
            print(
                f"  {item.name} ({group.adset_id}) [{where}]\n"
                f"    bugun: sarf {group.spend_minor}, natija {group.results}, "
                f"odatiy narx {usual if usual else '-'}, "
                f"narx {price_times(group) / 100:.1f}x, "
                f"chastota {group.frequency / 100 if group.frequency else '-'}, "
                f"o'rganishda {'ha' if group.learning else 'yo`q'}, "
                f"bizdan {'ha' if group.ours else 'yo`q'}, "
                f"{group.hours_running or 0:.0f} soat ishlagan"
            )
            found = judge(group)
            if not found:
                print("    topilma yo'q")
            for finding in found:
                print(
                    f"    -> {finding.kind}: {finding.action}, bosqich {finding.step}, "
                    f"{finding.times / 100:.1f}x, tavsiya {finding.advice}"
                )


def _findings(db, owner, *, since) -> None:
    rows = list(
        db.scalars(
            select(GuardAlert)
            .where(
                GuardAlert.owner_id == owner.id,
                (GuardAlert.closed_at.is_(None)) | (GuardAlert.updated_at >= since),
            )
            .order_by(GuardAlert.updated_at.desc())
        )
    )
    print(f"\n== Topilmalar ({len(rows)}) ==")
    if not rows:
        print("  yo'q")
    with override(owner.language or "uz"):
        for row in rows:
            state = "yopiq" if row.closed_at else "ochiq"
            told = "aytilgan" if row.said_step >= row.step else "hali aytilmagan"
            print(
                f"\n  [{state}, {told}] {row.name} - {row.kind}/{row.action}, "
                f"bosqich {row.step}, natija {row.result or '-'}"
            )
            print(f"    {guard_title(row)}")
            for line in guard_body(row).splitlines():
                print(f"    {line}")


def _telegram(db, owner, *, now, ignore_night: bool) -> None:
    from app.modules.notifications.bot import bot, is_configured
    from app.modules.notifications.constants import NoticeKind
    from app.modules.notifications.models import TelegramChat
    from app.modules.notifications.selectors import chats_wanting
    from app.modules.notifications.services.announce_guard import _announce, untold
    from app.modules.notifications.services.sweep import _asleep

    print("\n== Telegram ==")
    if not is_configured():
        print("  bot sozlanmagan - hech narsa yuborilmadi")
        return
    chat = db.scalars(
        chats_wanting(db, kind=NoticeKind.GUARD).where(
            TelegramChat.owner_id == owner.id
        )
    ).first()
    if chat is None:
        print("  Telegram ulanmagan (yoki obuna/sozlama yo'q) - hech narsa yuborilmadi")
        return
    rows = [row for row in untold(db) if row.owner_id == owner.id]
    if not rows:
        print("  yangi topilma yo'q - hech narsa yuborilmadi")
        return
    asleep = not ignore_night and str(owner.id) in {
        str(owner_id) for owner_id in _asleep(db, owner_ids={owner.id}, now=now)
    }
    if asleep:
        print(
            "  hozir ertalabki hisobot soatidan oldin: ogohlantirishlar kutadi (--ignore-night bilan yuboriladi)"
        )
    with bot() as client:
        sent = _announce(
            db, client=client, chat=chat, rows=rows, now=now, asleep=asleep
        )
    db.commit()
    waiting = [row for row in rows if row.action == "stop" and row.said_step < row.step]
    print(f"  yuborildi: {sent}")
    if waiting:
        print(
            f"  {len(waiting)} ta to'xtatish Meta javobini kutyapti: "
            "javob kelgach worker xabarni o'zi yuboradi"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The half-hourly guard for one owner.")
    parser.add_argument("email")
    parser.add_argument(
        "--look", action="store_true", help="Faqat ko'rsatadi, hech narsa yozmaydi."
    )
    parser.add_argument("--no-sync", action="store_true", help="Meta'dan o'qimaydi.")
    parser.add_argument(
        "--no-stop", action="store_true", help="To'xtatmaydi, faqat ogohlantiradi."
    )
    parser.add_argument(
        "--no-telegram", action="store_true", help="Telegram'ga yubormaydi."
    )
    parser.add_argument(
        "--ignore-night", action="store_true", help="Tunda ham ogohlantirish yuboradi."
    )
    args = parser.parse_args(argv)

    from app.modules.agent.selectors.policy import agent_owner_ids
    from app.modules.agent.services.run_guard import run_guard
    from app.modules.billing.selectors.subscription import has_live_subscription

    with task_session() as db:
        owner = _owner(db, args.email)
        if owner is None:
            print(f"{args.email}: bunday foydalanuvchi yo'q")
            return 1
        now = utcnow()
        print(f"{owner.email} - hozir {now:%Y-%m-%d %H:%M} UTC")
        if not has_live_subscription(db, owner=owner):
            print("Obuna faol emas: jadval bu egani tekshirmaydi. To'xtadim.")
            return 1
        agent_on = owner.id in agent_owner_ids(db, now=now)
        may_stop = agent_on and not args.no_stop
        print(
            f"Agent: {'yoqilgan' if agent_on else 'o`chirilgan'} - "
            f"{'to`xtatishi mumkin' if may_stop else 'faqat ogohlantiradi'}"
        )
        print("\n== Akkauntlar ==")
        accounts = _accounts(db, owner, now=now, sync=not args.no_sync)
        now = utcnow()
        if args.look:
            _look(db, owner, accounts, now=now)
            print("\n--look: hech narsa yozilmadi, to'xtatilmadi, yuborilmadi.")
            return 0
        started = now
        changed = run_guard(db, owner=owner, now=now, may_stop=may_stop)
        print(f"\nGuard: {changed} ta topilma ochildi yoki bosqichi o'zgardi")
        _findings(db, owner, since=started)
        if not args.no_telegram:
            _telegram(db, owner, now=utcnow(), ignore_night=args.ignore_night)
    return 0


if __name__ == "__main__":
    sys.exit(main())
