"""Customers whose CRM signals have no pixel to go to. Read-only."""

from collections import defaultdict

from sqlalchemy import func, select

from app import models as _models  # noqa: F401

from app.modules.accounts.models import User
from app.modules.crm.models import CrmSetup
from app.modules.crm.selectors import running_owners
from app.modules.integrations.models import AdAccount
from app.modules.leads.constants import SignalStatus
from app.modules.leads.models import LeadSignal
from app.modules.leads.selectors.reads import reporting_dataset
from app.worker import task_session

with task_session() as db:
    found = defaultdict(lambda: {"pending": 0, "crm": False})
    for owner_id, account_id, count in db.execute(
        select(LeadSignal.owner_id, LeadSignal.ad_account_id, func.count())
        .where(LeadSignal.status == SignalStatus.PENDING)
        .group_by(LeadSignal.owner_id, LeadSignal.ad_account_id)
    ):
        found[(owner_id, account_id)]["pending"] = count
    owners = running_owners(db)
    for setup in db.scalars(
        select(CrmSetup).where(
            CrmSetup.owner_id.in_(owners), CrmSetup.ad_account_id.is_not(None)
        )
    ) if owners else []:
        found[(setup.owner_id, setup.ad_account_id)]["crm"] = True

    rows = []
    for (owner_id, account_id), info in found.items():
        owner = db.get(User, owner_id)
        account = db.get(AdAccount, account_id)
        if owner is None or account is None:
            continue
        if reporting_dataset(db, owner=owner, ad_account=account):
            continue
        rows.append((info["pending"], info["crm"], owner, account))

    rows.sort(key=lambda r: -r[0])
    print("kutayotgan | CRM juftligi | ism | telefon | email | reklama akkaunti")
    for pending, crm, owner, account in rows:
        print(f"{pending} | {'ha' if crm else 'yoq'} | {owner.full_name} | "
              f"{owner.phone} | {owner.email} | {account.name} ({account.external_id})")
    print(f"\nJami: {len({r[2].id for r in rows})} mijoz, {len(rows)} akkaunt")
