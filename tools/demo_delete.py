"""Delete the showcase account ``tools.demo_seed`` wrote.

    python -m tools.demo_delete --email demo@example.com          # shows, changes nothing
    python -m tools.demo_delete --email demo@example.com --yes    # deletes

Only an account carrying the showcase mark is touched; any other address
is refused with nothing changed.
"""

import argparse
import sys

from app import models as _models  # noqa: F401
from app.common.db import SessionLocal
from app.common.deletion import ProtectedRows
from app.modules.demo import NotADemo, wipe


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete the showcase account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--yes", action="store_true", help="really delete")
    asked = parser.parse_args()
    with SessionLocal() as db:
        try:
            gone = wipe(db, email=asked.email)
        except NotADemo as refused:
            print(refused)
            return 1
        except ProtectedRows as held:
            db.rollback()
            print(f"O'chirilmadi: {held.table} jadvalida unga bog'langan qator bor.")
            return 1
        for label, rows in sorted(gone.items()):
            print(f"  {label}: {rows}")
        print(f"Jami: {sum(gone.values())} qator")
        if not asked.yes:
            db.rollback()
            print("Hech narsa o'chirilmadi. O'chirish uchun --yes qo'shing.")
            return 0
        db.commit()
    print("O'chirildi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
