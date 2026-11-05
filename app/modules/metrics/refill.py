"""Reads every Meta account's ninety days again, for a figure added later.

Run once after a deploy that adds a column the nightly read fills only for
its last fortnight:

    python -m app.modules.metrics.refill          # report only
    python -m app.modules.metrics.refill --apply  # queue the reads

Each account is one task on the sync queue, spaced apart so the accounts of
one Meta login do not spend its call budget at once. Nothing is deleted:
rows are upserted on the same key as the nightly read.
"""

import sys
from typing import Final

from sqlalchemy.orm import Session

from app.modules.integrations.models import AdAccount

PROVIDER: Final = "meta"
SPACING_SECONDS: Final = 90


def accounts(db: Session) -> list[AdAccount]:
    from app.modules.ads.selectors import nightly_swept_accounts

    return [one for one in nightly_swept_accounts(db) if one.provider == PROVIDER]


def queue(found: list[AdAccount]) -> int:
    from app.modules.metrics.tasks import refill_history_task

    for position, account in enumerate(found):
        refill_history_task.apply_async(
            args=[str(account.id)], countdown=position * SPACING_SECONDS
        )
    return len(found)


def main(argv: list[str]) -> int:
    from app import models as _models  # noqa: F401
    from app.common.db import SessionLocal

    with SessionLocal() as db:
        found = accounts(db)
        print(f"Meta hisoblari: {len(found)}")
        if "--apply" in argv:
            minutes = len(found) * SPACING_SECONDS // 60
            print(f"Navbatga qo'yildi: {queue(found)}, taxminan {minutes} daqiqada.")
        else:
            print("Faqat hisobot: navbatga qo'yish uchun --apply bering.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
