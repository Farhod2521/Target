"""Why a customer's leads do not land on the CRM board. Read-only.

    docker compose exec -T api python - email@misol.uz < tools/crm_check.py
    docker compose exec -T api python - email@misol.uz 14 < tools/crm_check.py

The second argument is how many days back to look (7 by default).
"""

import sys
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select

from app import models as _models  # noqa: F401

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.selectors.owned import campaigns_by_pair
from app.modules.crm.models import CrmCard, CrmSetup, CrmStage
from app.modules.crm.selectors import Scope, pair_conditions
from app.modules.crm.services import card_for_phone, takes_lead
from app.modules.integrations.selectors.pairs import page_pairs
from app.modules.leads.models import Lead
from app.modules.leads.selectors import subscribed_lead_scope
from app.worker import task_session

SHOWN = 40


def reason(db, *, lead, pairs, conditions, setups, stages, paid) -> str:
    if lead.is_test:
        return "test lid"
    if lead.is_organic:
        return "organik lid (reklamasiz)"
    if db.scalar(select(Lead.id).where(Lead.id == lead.id, paid)) is None:
        return "lid sahifasi yoqilgan (to'langan) sahifalar ichida emas"
    pair = None
    for each in pairs:
        condition = conditions.get(each.key)
        if condition is not None and db.scalar(
            select(Lead.id).where(Lead.id == lead.id, condition)
        ):
            pair = each
            break
    if pair is None:
        return "kampaniya platformadan yoqilmagan (yoki boshqa juftlikniki)"
    setup = setups.get(pair.key)
    if setup is None:
        return f"juftlikda CRM sozlanmagan: {pair.page.name}"
    if setup.state != "on":
        return f"CRM yoqilmagan (state={setup.state}): {pair.page.name}"
    if setup.leads_since is not None and lead.submitted_at < setup.leads_since:
        return f"lid CRM boshlanish sanasidan oldin ({setup.leads_since:%Y-%m-%d %H:%M})"
    if not takes_lead(setup=setup, lead=lead):
        return "reklama CRM sozlamasida tanlanmagan"
    if not stages.get(pair.key):
        return "doskada «Yangi» ustuni yo'q"
    if card_for_phone(db, setup=setup, lead=lead) is not None:
        return "shu telefon bilan karta bor - eski kartaga qo'shilgan"
    return "TO'SIQ YO'Q - tushishi kerak edi (worker/navbatni tekshiring)"


def main(email: str, days: int) -> None:
    now = utcnow()
    since = now - timedelta(days=days)
    with task_session() as db:
        user = db.scalars(
            select(User).where(func.lower(User.email) == email.lower())
        ).first()
        if user is None:
            print("XATO foydalanuvchi topilmadi:", email)
            return
        print(f"Foydalanuvchi: {user.email} id={user.id}")
        pairs = page_pairs(db, owner=user)
        conditions = pair_conditions(db, owner=user, pairs=pairs)
        campaigns = campaigns_by_pair(db, owner=user, pairs=pairs)
        paid = subscribed_lead_scope(db, owner=user)
        setups, stages = {}, {}
        print(f"\nJuftliklar ({len(pairs)}):")
        for pair in pairs:
            scope = Scope.of(pair)
            setup = db.scalar(select(CrmSetup).where(scope.holds(CrmSetup)))
            setups[pair.key] = setup
            stages[pair.key] = db.scalar(
                select(func.count())
                .select_from(CrmStage)
                .where(scope.holds(CrmStage), CrmStage.kind == "new")
            )
            own = campaigns.get(pair.key)
            print(
                f"  - {pair.page.name} + {pair.account.name}"
                f" | saqlangan={pair.stored}"
                f" | kampaniya={len(own.exact) if own else 0}"
                f" (+{len(own.pageless) if own else 0} sahifasiz)"
            )
            if setup is None:
                print("      CRM: sozlanmagan")
            else:
                print(
                    f"      CRM: state={setup.state} enabled_at={setup.enabled_at}"
                    f" leads_since={setup.leads_since} every_ad={setup.every_ad}"
                    f" take_new_ads={setup.take_new_ads}"
                    f" tanlangan={len(setup.ad_external_ids or [])}"
                    f" «Yangi» ustun={stages[pair.key]}"
                )

        total = db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.owner_id == user.id, Lead.received_at >= since)
        )
        placed = select(CrmCard.lead_id).where(CrmCard.owner_id == user.id)
        missing = list(
            db.scalars(
                select(Lead)
                .where(
                    Lead.owner_id == user.id,
                    Lead.received_at >= since,
                    Lead.id.not_in(placed),
                )
                .order_by(Lead.received_at.desc())
            )
        )
        print(
            f"\nOxirgi {days} kun: lid={total}, doskada={total - len(missing)},"
            f" doskada yo'q={len(missing)}"
        )
        counts: Counter[str] = Counter()
        rows = []
        for lead in missing:
            why = reason(
                db,
                lead=lead,
                pairs=pairs,
                conditions=conditions,
                setups=setups,
                stages=stages,
                paid=paid,
            )
            counts[why] += 1
            rows.append((lead, why))
        print("\nSabablar:")
        for why, count in counts.most_common():
            print(f"  {count:>5}  {why}")
        print(f"\nOxirgi {min(SHOWN, len(rows))} ta lid:")
        for lead, why in rows[:SHOWN]:
            print(
                f"  {lead.received_at:%m-%d %H:%M} kampaniya={lead.campaign_external_id}"
                f" ad={lead.ad_external_id} | {why}"
            )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("email kerak")
    else:
        main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 7)
