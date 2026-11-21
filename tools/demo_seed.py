"""Write the showcase account: one made-up customer who uses everything.

    python -m tools.demo_seed --email demo@example.com --password 'Parol123!'

A learning centre with sixty days behind it: adverts and their numbers,
leads, a CRM board three managers worked, bills. Nothing of it exists at
Meta and nothing is sent there. The managers sign in with the same
password. Take it away with ``python -m tools.demo_delete``; to bring the
dates up to today, delete it and write it again.
"""

import argparse
import sys

from app import models as _models  # noqa: F401
from app.common.db import SessionLocal
from app.modules.accounts.exceptions import EmailTaken
from app.modules.demo import seed


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the showcase account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    asked = parser.parse_args()
    if len(asked.password) < 8:
        print("Parol kamida 8 belgi bo'lsin.")
        return 2
    with SessionLocal() as db:
        try:
            made = seed(db, email=asked.email, password=asked.password)
        except EmailTaken:
            print(
                "Bu email (yoki uning +sotuvN manzili) band. Avval "
                "`python -m tools.demo_delete --email ...` yoki boshqa email."
            )
            return 1
        db.commit()
    print("Namoyish akkaunti yozildi.")
    print(f"  Ega:        {made.owner_email}")
    for address in made.manager_emails:
        print(f"  Menejer:    {address}")
    print("  Parol:      hammasi uchun siz bergan parol")
    print(f"  Tarif:      {made.plan}")
    print(f"  Kampaniya:  {made.campaigns}")
    print(f"  Lid:        {made.leads}, karta: {made.cards}, sotuv: {made.sales}")
    print(f"  Raqam qatorlari: {made.metric_rows}")
    if not made.rates:
        print(
            "DIQQAT: Markaziy bank kurslari bazada yo'q, dollardagi sarf "
            "so'mga o'girilmaydi. Avval: python -m app.modules.metrics.rates"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
