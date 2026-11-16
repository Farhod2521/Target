"""Write the page's and campaign's names into the guard's open findings.

    python -m tools.guard_place_backfill          # shows what would change, changes nothing
    python -m tools.guard_place_backfill --yes    # writes it

Findings written before 8662df3 name only the group, so the cabinet line has
no «Sahifa / Kampaniya». This fills those two names into every open finding
that lacks them. Nothing is sent to Telegram, nothing is deleted, a stopped
group stays stopped and its buttons keep working.
"""

import argparse
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401
from app.common.db import SessionLocal
from app.modules.accounts.models import User
from app.modules.ads.models import Campaign
from app.modules.agent.models import GuardAlert
from app.modules.agent.selectors.guard import _page_names


def fill(db: Session) -> tuple[int, int]:
    """Fill the names in. Returns (open findings looked at, findings changed)."""
    rows = list(db.scalars(select(GuardAlert).where(GuardAlert.closed_at.is_(None))))
    by_owner: dict[object, list[GuardAlert]] = defaultdict(list)
    for row in rows:
        figures = row.figures or {}
        if not (figures.get("page_name") and figures.get("campaign_name")):
            by_owner[row.owner_id].append(row)
    changed = 0
    for owner_id, waiting in by_owner.items():
        owner = db.get(User, owner_id)
        if owner is None:
            continue
        pages = _page_names(
            db, owner=owner, adset_ids=sorted({r.adset_external_id for r in waiting})
        )
        campaigns = dict(
            db.execute(
                select(Campaign.external_id, Campaign.name).where(
                    Campaign.owner_id == owner.id,
                    Campaign.external_id.in_({r.campaign_external_id for r in waiting}),
                )
            ).all()
        )
        for row in waiting:
            figures = dict(row.figures or {})
            page = figures.get("page_name") or pages.get(row.adset_external_id, "")
            campaign = figures.get("campaign_name") or (
                campaigns.get(row.campaign_external_id) or row.campaign_external_id
            )
            if (page, campaign) == (
                figures.get("page_name") or "",
                figures.get("campaign_name") or "",
            ):
                continue
            figures["page_name"], figures["campaign_name"] = page, campaign
            row.figures = figures
            changed += 1
            print(
                f"{row.id}  {row.kind:<9} sahifa={page or '-'!r}  "
                f"kampaniya={campaign or '-'!r}  guruh={row.name!r}"
            )
    db.flush()
    return len(rows), changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Name page and campaign in open guard findings."
    )
    parser.add_argument("--yes", action="store_true", help="Really write it.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        looked, changed = fill(db)
        print(f"\nOchiq topilmalar: {looked}, to'ldiriladigan: {changed}.")
        if not args.yes:
            db.rollback()
            print("Hech narsa o'zgarmadi. Yozish uchun --yes qo'shing.")
            return 0
        db.commit()
        print("Yozildi. Telegramga hech narsa ketmadi.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
