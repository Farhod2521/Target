"""What the nightly check against Ads Manager found, account by account.

    python -m app.modules.metrics.check            # the last 7 days checked
    python -m app.modules.metrics.check --days 30

Every account checked, how many of its days were checked, and each day
whose figures are apart from Meta's own account total, with the figures
that are. Read only.
"""

import sys
from datetime import timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import CHECK_DAYS
from app.modules.metrics.models import MetricsCheck
from app.modules.metrics.services.check import CHECKED, apart

LABELS: Final[dict[str, str]] = {
    "spend_minor": "Sarf (minor)",
    "impressions": "Ko'rsatildi",
    "clicks": "Klik",
    "link_clicks": "Link klik",
    "purchases_site": "Sotuv (sayt)",
}


def report(db: Session, *, days: int) -> list[str]:
    since = utcnow().date() - timedelta(days=days)
    rows = db.execute(
        select(MetricsCheck, AdAccount.external_id, AdAccount.name)
        .join(AdAccount, AdAccount.id == MetricsCheck.ad_account_id)
        .where(MetricsCheck.day >= since)
        .order_by(AdAccount.external_id, MetricsCheck.day)
    ).all()
    lines: list[str] = []
    accounts: dict[str, list[MetricsCheck]] = {}
    names: dict[str, str] = {}
    for check, external_id, name in rows:
        accounts.setdefault(external_id, []).append(check)
        names[external_id] = name
    apart_days = 0
    for external_id, checks in accounts.items():
        wrong = [one for one in checks if one.differs]
        apart_days += len(wrong)
        lines.append(
            f"{external_id} {names[external_id]}: {len(checks)} kun, "
            f"{len(wrong)} tasi farq qiladi"
        )
        for one in wrong:
            gaps = ", ".join(
                f"{LABELS[key]} biz {one.ours.get(key, 0)} / Meta {one.theirs.get(key, 0)}"
                for key in CHECKED
                if apart(one.ours.get(key, 0), one.theirs.get(key, 0))
            )
            lines.append(f"  {one.day.isoformat()}: {gaps}")
    lines.append(
        f"Jami: {len(accounts)} hisob, {sum(len(c) for c in accounts.values())} kun, "
        f"{apart_days} kun farq qiladi"
    )
    return lines


def main(argv: list[str]) -> int:
    from app import models as _models  # noqa: F401
    from app.common.db import SessionLocal

    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else CHECK_DAYS
    with SessionLocal() as db:
        for line in report(db, days=days):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
