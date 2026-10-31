"""Delete a test payment from the database, by its transaction id.

    python -m tools.erase_payment <id>          # shows what would go, changes nothing
    python -m tools.erase_payment <id> --yes    # deletes it

``<id>`` is ``transaction.id`` from ``GET /office/payments/invoices``, the
provider's id, the reference, or the invoice number (``TA-…``). A payment
written by hand has no transaction: use its invoice number.
"""

import argparse
import sys

from app import models as _models  # noqa: F401
from app.common.db import SessionLocal
from app.modules.backoffice.services.erase_payment import (
    ErasedPayment,
    erase_payment,
    invoices_for,
)


def report(erased: ErasedPayment) -> str:
    return "\n".join(
        (
            f"Hisob: {erased.number} ({erased.status})",
            f"Mijoz: {erased.email or '-'}",
            f"Summa: {erased.amount_minor} {erased.currency} (minor)",
            f"To'lov urinishlari: {erased.attempts}",
            f"Referal mukofotlari: {erased.rewards}",
            f"Sotuv komissiyalari: {erased.commissions}",
            f"Hamyon yechimlari: {erased.wallet_spends}",
            f"Obuna tarixidan uzildi: {erased.changes_unlinked}",
            f"Promo yozuvidan uzildi: {erased.promos_unlinked}",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete a test payment.")
    parser.add_argument("id", help="Transaction id, reference or invoice number.")
    parser.add_argument("--yes", action="store_true", help="Really delete it.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        found = invoices_for(db, key=args.id.strip())
        if not found:
            print("Topilmadi.", file=sys.stderr)
            return 1
        if len(found) > 1:
            numbers = ", ".join(invoice.number for invoice in found)
            print(f"Bir nechta hisob topildi: {numbers}.", file=sys.stderr)
            print("Hisob raqami bilan qayta yuboring.", file=sys.stderr)
            return 1
        print(report(erase_payment(db, invoice=found[0])))
        if not args.yes:
            db.rollback()
            print("\nHech narsa o'zgarmadi. O'chirish uchun --yes qo'shing.")
            return 0
        db.commit()
        print("\nO'chirildi. Obuna kunlari o'zgarmadi.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
