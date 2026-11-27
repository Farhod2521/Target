"""How often the kind guessed from a page is the kind its owner chose. Read-only.

    python tools/kind_guess_eval.py            # 60 businesses
    python tools/kind_guess_eval.py 322        # all of them

Takes the businesses whose owner picked a listed kind in the old setup form
(a direction, no custom label), asks the model for the kind from the page
alone - exactly as ``businesses.services.guess`` does for a new profile -
and compares. Nothing is written: no guess is kept, no call is recorded.
Needs ``ANTHROPIC_API_KEY`` in the environment; every business is one short
call.
"""

import sys
from collections import Counter

from sqlalchemy import select

from app import models as _models  # noqa: F401
from app.modules.businesses.models import Business, BusinessCategory
from app.modules.businesses.services.guess import ask, page_words
from app.modules.integrations.models import PageAccount
from app.worker import task_session

DEFAULT = 60


def main(limit: int) -> None:
    with task_session() as db:
        rows = db.execute(
            select(Business, PageAccount, BusinessCategory)
            .join(PageAccount, PageAccount.id == Business.page_id)
            .join(BusinessCategory, BusinessCategory.id == Business.direction_id)
            .where(Business.custom_category_id.is_(None))
            .order_by(Business.created_at)
            .limit(limit)
        ).all()
        asked = right = empty = failed = 0
        tokens_out = cost = 0
        wrong: Counter[tuple[str, str]] = Counter()
        for business, page, direction in rows:
            if not page_words(page):
                continue
            try:
                result = ask(db, page=page)
            except Exception as exc:
                failed += 1
                print(f"!! {business.name[:40]}: {type(exc).__name__}")
                continue
            if result is None:
                continue
            asked += 1
            guess = result.value
            tokens_out += result.output_tokens
            cost += result.cost_micros
            hit = guess.direction == direction.key
            right += hit
            empty += not guess.direction
            if not hit:
                wrong[(direction.key, guess.direction or "-")] += 1
                print(
                    f"-- {business.name[:40]!r}: owner {direction.key}, "
                    f"guess {guess.direction or '-'} / {guess.subtype or '-'}"
                )
        db.rollback()
    if not asked:
        print("Nothing asked.")
        return
    print()
    print(f"Asked: {asked}; failed calls: {failed}")
    print(f"Same kind as the owner chose: {right} ({right * 100 // asked}%)")
    print(f"No kind given (page says too little): {empty}")
    answered = asked - empty
    if answered:
        print(f"Of those answered: {right} of {answered} ({right * 100 // answered}%)")
    print(f"Output tokens per call: {tokens_out // asked}")
    print(f"Cost: {cost / 1_000_000:.4f} (the ledger's currency)")
    print("Most common mismatches (owner -> guess):")
    for (owner_key, guess_key), count in wrong.most_common(10):
        print(f"  {owner_key} -> {guess_key}: {count}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT)
