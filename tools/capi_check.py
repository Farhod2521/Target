"""Did the night CAPI send work? Read-only, changes nothing.

    docker compose exec -T api python - < tools/capi_check.py
    docker compose exec -T api python - 3 < tools/capi_check.py

The argument is how many nights back to look (1 = last night).
"""

import sys
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, select

from app import models as _models  # noqa: F401

from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.crm.models import CrmCard, CrmSetup
from app.modules.crm.selectors import running_owners
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors import owner_clocks
from app.modules.leads.constants import SignalStatus
from app.modules.leads.models import LeadSignal
from app.modules.leads.selectors.reads import reporting_dataset
from app.modules.leads.services.signals import account_token
from app.worker import task_session

NIGHTS = int(sys.argv[1]) if len(sys.argv) > 1 else 1


def email(db, owner_id) -> str:
    user = db.get(User, owner_id)
    return user.email if user else str(owner_id)


def blocker(db, owner_id, account_id) -> str:
    account = db.get(AdAccount, account_id)
    if account is None:
        return "akkaunt yo'q"
    owner = db.get(User, owner_id)
    if not reporting_dataset(db, owner=owner, ad_account=account):
        return "piksel tanlanmagan"
    if account_token(account) is None:
        return "ulanish ishlamaydi"
    return "to'siq yo'q (navbatda/xato)"


with task_session() as db:
    now = utcnow()
    since = now - timedelta(days=NIGHTS)
    print(f"Hozir {now:%Y-%m-%d %H:%M} UTC, {NIGHTS} kecha\n")

    print("== Sozlama ==")
    print(f"ADS_DRY_RUN={settings.ads_dry_run}  (True bo'lsa hech narsa yuborilmaydi)")
    test = settings.meta_conversions_test_code
    print(f"META_CONVERSIONS_TEST_CODE={'BOR: ' + test if test else 'yoq'}"
          "  (bor bo'lsa hammasi Test Events'ga ketadi)\n")

    print("== 1. Foydalanuvchilar ==")
    on = set(running_owners(db))
    with_cards = set(db.scalars(
        select(CrmCard.owner_id).where(CrmCard.owner_id.in_(on)).distinct()
    )) if on else set()
    with_pixel = set()
    for setup in db.scalars(
        select(CrmSetup).where(CrmSetup.owner_id.in_(on), CrmSetup.ad_account_id.is_not(None))
    ) if on else []:
        account = db.get(AdAccount, setup.ad_account_id)
        owner = db.get(User, setup.owner_id)
        if account and reporting_dataset(db, owner=owner, ad_account=account):
            with_pixel.add(setup.owner_id)
    any_signal = set(db.scalars(select(LeadSignal.owner_id).distinct()))
    ever_sent = set(db.scalars(
        select(LeadSignal.owner_id).where(LeadSignal.status == SignalStatus.SENT).distinct()
    ))
    sent_now = set(db.scalars(
        select(LeadSignal.owner_id)
        .where(LeadSignal.status == SignalStatus.SENT, LeadSignal.sent_at >= since)
        .distinct()
    ))
    print(f"CRM yoqilgan egalar:             {len(on)}")
    print(f"  kartasi bor:                   {len(with_cards)}")
    print(f"  CRM juftligida piksel tanlangan: {len(with_pixel)}")
    print(f"Signal navbatiga tushgan egalar: {len(any_signal)}")
    print(f"Hech bo'lmasa 1 marta yuborilgan: {len(ever_sent)}")
    print(f"Shu {NIGHTS} kechada yuborilgan:   {len(sent_now)}\n")

    print(f"== 2. Shu {NIGHTS} kechada yuborilganlar ==")
    rows = db.execute(
        select(LeadSignal.owner_id, LeadSignal.stage, LeadSignal.dataset_id,
               LeadSignal.trace_id, LeadSignal.sent_at)
        .where(LeadSignal.status == SignalStatus.SENT, LeadSignal.sent_at >= since)
    ).all()
    per = defaultdict(lambda: {"stages": Counter(), "datasets": set(), "traces": set(), "at": set()})
    for owner_id, stage, dataset, trace, sent_at in rows:
        p = per[owner_id]
        p["stages"][stage] += 1
        p["datasets"].add(dataset)
        p["traces"].add(trace)
        p["at"].add(sent_at)
    clocks = owner_clocks(db, owner_ids=list(per))
    for owner_id, p in sorted(per.items(), key=lambda x: -sum(x[1]["stages"].values())):
        clock = clocks[str(owner_id)]
        times = sorted(t.astimezone(clock).strftime("%m-%d %H:%M") for t in p["at"])
        empty = "" in p["traces"]
        print(f"- {email(db, owner_id)}: {sum(p['stages'].values())} ta "
              f"{dict(p['stages'])} piksel={sorted(p['datasets'])} "
              f"trace={len(p['traces'])}{' (BO`SH trace bor!)' if empty else ''} "
              f"vaqt(egasi soati)={times[0]}..{times[-1]}")
    if not rows:
        print("(hech narsa yuborilmagan)")
    print(f"Jami: {len(rows)} ta signal\n")

    print("== 3. Muammolar ==")
    failed = db.execute(
        select(LeadSignal.owner_id, LeadSignal.last_error, func.count())
        .where(LeadSignal.status == SignalStatus.FAILED,
               LeadSignal.updated_at >= now - timedelta(days=30))
        .group_by(LeadSignal.owner_id, LeadSignal.last_error)
    ).all()
    print(f"Meta rad etgan (30 kun): {sum(c for *_, c in failed)}")
    for owner_id, error, count in failed:
        print(f"  - {email(db, owner_id)}: {count} ta - {error[:200]}")

    stuck = db.execute(
        select(LeadSignal.owner_id, LeadSignal.ad_account_id, func.count(),
               func.min(LeadSignal.occurred_at))
        .where(LeadSignal.status == SignalStatus.PENDING,
               LeadSignal.occurred_at < now - timedelta(days=1, hours=6))
        .group_by(LeadSignal.owner_id, LeadSignal.ad_account_id)
    ).all()
    print(f"Yuborilishi kerak edi, lekin kutib qolgan: {sum(r[2] for r in stuck)}")
    for owner_id, account_id, count, oldest in stuck:
        print(f"  - {email(db, owner_id)}: {count} ta, eng eskisi {oldest:%m-%d}, "
              f"sabab: {blocker(db, owner_id, account_id)}")

    expired = db.scalar(
        select(func.count()).select_from(LeadSignal)
        .where(LeadSignal.status == SignalStatus.EXPIRED,
               LeadSignal.updated_at >= now - timedelta(days=30))
    )
    print(f"Muddati o'tib yuborilmay qolgan (30 kun): {expired}")

    silent = []
    for owner_id in with_cards:
        recent = db.scalar(
            select(func.count()).select_from(CrmCard)
            .where(CrmCard.owner_id == owner_id,
                   CrmCard.created_at >= now - timedelta(days=7),
                   CrmCard.created_at < now - timedelta(days=1, hours=6),
                   CrmCard.lead_id.is_not(None))
        )
        signals = db.scalar(
            select(func.count()).select_from(LeadSignal)
            .where(LeadSignal.owner_id == owner_id,
                   LeadSignal.created_at >= now - timedelta(days=7))
        )
        if recent and not signals:
            silent.append((owner_id, recent))
    print(f"Kartasi bor, lekin 7 kunda bitta ham signal yig'ilmagan: {len(silent)}")
    for owner_id, count in silent:
        print(f"  - {email(db, owner_id)}: {count} ta karta")
