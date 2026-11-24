"""Gives every stored page and ad account pair its business.

Run once after migration 0081, and again whenever wanted:

    python -m app.modules.businesses.backfill          # report only
    python -m app.modules.businesses.backfill --apply  # write

The report run does the same work inside a transaction and rolls it back,
so its numbers are the ones ``--apply`` would write. Nothing is deleted and
no page, account or pair column is touched: see
:mod:`app.modules.businesses.services.links` for what is written.
"""

import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.businesses.services.links import (
    Synced,
    _pair_rows,
    fill_rows,
    sync_links,
)
from app.modules.integrations.models import PagePair


def link_everyone(db: Session) -> Synced:
    total = Synced()
    owners = db.scalars(
        select(PagePair.owner_id).distinct().order_by(PagePair.owner_id)
    ).all()
    for owner_id in owners:
        total.add(sync_links(db, owner_id=owner_id))
    return total


def left_empty(db: Session) -> dict[str, int]:
    """Rows that name a page and still have no business, per table."""
    from app.modules.leads.models import Lead

    left = {}
    for table in _pair_rows():
        left[table.name] = db.scalar(
            select(func.count())
            .select_from(table)
            .where(table.c.business_id.is_(None), table.c.page_id.is_not(None))
        )
    left["leads"] = db.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.business_id.is_(None), Lead.form_id.is_not(None))
    )
    return {name: int(count or 0) for name, count in left.items()}


def report(done: Synced, filled: dict[str, int], left: dict[str, int]) -> None:
    pairs = done.kept + done.bound + done.opened + done.moved
    print(f"Juftliklar biznesga bog'landi: {pairs}")
    print(f"  avvaldan bog'langan: {done.kept}")
    print(f"  sahifa profiliga bog'landi: {done.bound}")
    print(f"  ikkinchi juftlik uchun yangi biznes: {done.opened}")
    print(f"  akkaunti almashgan: {done.moved}")
    print(f"Yopilgan bog'lanishlar (juftlik o'chirilgan): {done.closed}")
    print(f"Profili yo'q sahifa, kutmoqda: {done.waiting}")
    print(f"Bog'lab bo'lmadi (akkaunt boshqa biznes kaliti): {done.blocked}")
    print("Qatorlarga biznes yozildi / sahifasi bor, biznesi yo'q qoldi:")
    for name in sorted(filled):
        print(f"  {name}: {filled[name]} / {left.get(name, 0)}")


def main(argv: list[str]) -> int:
    from app import models as _models  # noqa: F401
    from app.common.db import SessionLocal

    with SessionLocal() as db:
        done = link_everyone(db)
        filled = fill_rows(db)
        report(done, filled, left_empty(db))
        if "--apply" in argv:
            db.commit()
            print("Yozildi.")
        else:
            db.rollback()
            print("Faqat hisobot: yozish uchun --apply bering.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
